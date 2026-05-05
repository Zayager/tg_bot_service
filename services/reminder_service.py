"""Сервис для напоминаний"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import List
from aiogram import Bot
from database import db
from services.appointment_service import AppointmentService
from services.bot_settings_service import BotSettingsService
from utils.timezone import format_datetime, format_date, get_current_datetime_in_master_tz, convert_to_master_timezone
import pytz
from config import BOT_TOKEN

logger = logging.getLogger(__name__)

class ReminderService:
    """Сервис для управления напоминаниями"""
    
    @staticmethod
    async def schedule_reminders_for_appointment(appointment_id: int, appointment_date: datetime):
        """Создать напоминания для записи"""
        settings = await BotSettingsService.get_appointment_settings()
        
        # Убеждаемся, что appointment_date имеет timezone (конвертируем в часовой пояс мастера)
        if appointment_date.tzinfo is None:
            # Если naive, считаем что это уже в часовом поясе мастера
            from utils.timezone import get_master_timezone
            master_tz = get_master_timezone()
            appointment_date = master_tz.localize(appointment_date)
        else:
            appointment_date = convert_to_master_timezone(appointment_date)
        
        current_time = get_current_datetime_in_master_tz()
        
        # Напоминание за 24 часа
        if settings['reminder_24h_enabled']:
            reminder_24h_time = appointment_date - timedelta(hours=24)
            if reminder_24h_time > current_time:
                # Конвертируем в UTC для сохранения в БД (PostgreSQL хранит как timestamp without time zone)
                reminder_24h_utc = reminder_24h_time.astimezone(pytz.UTC).replace(tzinfo=None)
                await db.execute("""
                    INSERT INTO reminders (appointment_id, reminder_type, scheduled_at)
                    VALUES ($1, '24h', $2)
                """, appointment_id, reminder_24h_utc)
        
        # Напоминание за 1-2 часа
        if settings['reminder_1_2h_enabled']:
            reminder_1_2h_time = appointment_date - timedelta(hours=2)
            if reminder_1_2h_time > current_time:
                # Конвертируем в UTC для сохранения в БД
                reminder_1_2h_utc = reminder_1_2h_time.astimezone(pytz.UTC).replace(tzinfo=None)
                await db.execute("""
                    INSERT INTO reminders (appointment_id, reminder_type, scheduled_at)
                    VALUES ($1, '1-2h', $2)
                """, appointment_id, reminder_1_2h_utc)
    
    @staticmethod
    async def check_and_send_reminders(bot: Bot):
        """Проверить и отправить напоминания, которые должны быть отправлены"""
        now = get_current_datetime_in_master_tz()
        # Конвертируем в UTC naive для сравнения с БД
        now_utc_naive = now.astimezone(pytz.UTC).replace(tzinfo=None)
        
        # Получаем напоминания, которые нужно отправить
        reminders = await db.fetch("""
            SELECT r.*, a.client_id, a.appointment_date, a.service_id
            FROM reminders r
            JOIN appointments a ON r.appointment_id = a.id
            WHERE r.scheduled_at <= $1
            AND r.sent = FALSE
            AND a.status IN ('pending', 'confirmed')
        """, now_utc_naive)
        
        for reminder in reminders:
            try:
                appointment = await AppointmentService.get_appointment(reminder['appointment_id'])
                if not appointment:
                    continue
                
                client_user = await db.fetchrow(
                    "SELECT telegram_id, full_name FROM users WHERE id = $1",
                    appointment.client_id
                )
                
                if not client_user:
                    continue
                
                # Формируем сообщение напоминания
                if reminder['reminder_type'] == '24h':
                    message = (
                        f"🔔 <b>Напоминание о записи</b>\n\n"
                        f"Через 24 часа у вас запись!\n\n"
                        f"Дата: {format_date(appointment.appointment_date)}\n"
                        f"Время: {format_datetime(appointment.appointment_date, '%H:%M')}\n\n"
                        f"Пожалуйста, подтвердите, что придете:"
                    )
                elif reminder['reminder_type'] == '1-2h':
                    message = (
                        f"🔔 <b>Напоминание о записи</b>\n\n"
                        f"Через 1-2 часа у вас запись!\n\n"
                        f"Дата: {format_date(appointment.appointment_date)}\n"
                        f"Время: {format_datetime(appointment.appointment_date, '%H:%M')}\n\n"
                        f"Пожалуйста, подтвердите, что придете:"
                    )
                else:
                    continue
                
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Подтвердить, что приду",
                            callback_data=f"confirm_attendance_{appointment.id}"
                        )
                    ]
                ])
                
                await bot.send_message(
                    client_user['telegram_id'],
                    message,
                    reply_markup=keyboard,
                    parse_mode='HTML'
                )
                
                # Помечаем напоминание как отправленное
                await db.execute("""
                    UPDATE reminders SET sent = TRUE, sent_at = CURRENT_TIMESTAMP
                    WHERE id = $1
                """, reminder['id'])
                
            except Exception as e:
                logger.error(f"Ошибка отправки напоминания {reminder['id']}: {e}")
                # Помечаем как отправленное, чтобы не повторять бесконечно
                await db.execute("""
                    UPDATE reminders SET sent = TRUE, sent_at = CURRENT_TIMESTAMP
                    WHERE id = $1
                """, reminder['id'])
    
    @staticmethod
    async def handle_follow_up_reminders(bot: Bot):
        """Обработка повторных напоминаний для неподтвержденных записей"""
        settings = await BotSettingsService.get_appointment_settings()
        interval_hours = settings['reminder_interval_hours']
        
        # Получаем записи с отправленными напоминаниями за 1-2ч, которые не были подтверждены
        # и для которых прошло больше интервала с последнего напоминания
        now = get_current_datetime_in_master_tz()
        now_utc_naive = now.astimezone(pytz.UTC).replace(tzinfo=None)
        interval_time = now - timedelta(hours=interval_hours)
        interval_utc_naive = interval_time.astimezone(pytz.UTC).replace(tzinfo=None)
        
        reminders = await db.fetch("""
            SELECT r.*, a.client_id, a.appointment_date
            FROM reminders r
            JOIN appointments a ON r.appointment_id = a.id
            WHERE r.reminder_type = '1-2h'
            AND r.sent = TRUE
            AND a.status IN ('pending', 'confirmed')
            AND a.appointment_date > $1
            AND r.sent_at < $2
            AND NOT EXISTS (
                SELECT 1 FROM reminders r2
                WHERE r2.appointment_id = r.appointment_id
                AND r2.reminder_type = 'follow_up'
                AND r2.sent_at > $3
            )
        """, now_utc_naive, interval_utc_naive, interval_utc_naive)
        
        for reminder in reminders:
            try:
                appointment = await AppointmentService.get_appointment(reminder['appointment_id'])
                if not appointment:
                    continue
                
                client_user = await db.fetchrow(
                    "SELECT telegram_id FROM users WHERE id = $1",
                    appointment.client_id
                )
                
                if not client_user:
                    continue
                
                message = (
                    f"🔔 <b>Повторное напоминание</b>\n\n"
                    f"У вас скоро запись!\n\n"
                    f"Дата: {format_date(appointment.appointment_date)}\n"
                    f"Время: {format_datetime(appointment.appointment_date, '%H:%M')}\n\n"
                    f"Пожалуйста, подтвердите, что придете:"
                )
                
                from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Подтвердить, что приду",
                            callback_data=f"confirm_attendance_{appointment.id}"
                        )
                    ]
                ])
                
                await bot.send_message(
                    client_user['telegram_id'],
                    message,
                    reply_markup=keyboard,
                    parse_mode='HTML'
                )
                
                # Создаем запись о повторном напоминании
                await db.execute("""
                    INSERT INTO reminders (appointment_id, reminder_type, scheduled_at, sent, sent_at)
                    VALUES ($1, 'follow_up', CURRENT_TIMESTAMP, TRUE, CURRENT_TIMESTAMP)
                """, appointment.id)
                
                # Уведомляем мастера о неподтвержденной записи
                from config import ADMIN_ID
                from services.notification_service import notify_master_new_booking
                await bot.send_message(
                    ADMIN_ID,
                    f"⚠️ Клиент не подтвердил запись на {format_datetime(appointment.appointment_date)}. Отправлено повторное напоминание."
                )
                
            except Exception as e:
                logger.error(f"Ошибка отправки повторного напоминания: {e}")

async def reminder_worker(bot: Bot):
    """Фоновый процесс для проверки и отправки напоминаний"""
    import logging
    logger = logging.getLogger(__name__)
    
    while True:
        try:
            await ReminderService.check_and_send_reminders(bot)
            await ReminderService.handle_follow_up_reminders(bot)
        except Exception as e:
            logger.error(f"Ошибка в reminder_worker: {e}")
        
        # Проверяем каждую минуту
        await asyncio.sleep(60)

