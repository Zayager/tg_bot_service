"""Сервис для уведомлений"""
from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from models import Appointment
from services.service_service import ServiceService
from utils.timezone import format_datetime, format_date
from database import db
from config import ADMIN_ID

async def notify_master_new_booking(appointment: Appointment, bot: Bot):
    """Уведомить мастера о новой записи"""
    service = await ServiceService.get_service(appointment.service_id)
    client_user = await db.fetchrow(
        "SELECT * FROM users WHERE id = $1",
        appointment.client_id
    )
    
    message = (
        f"🔔 <b>Новая запись!</b>\n\n"
        f"Клиент: {client_user['full_name'] or client_user['username'] or 'Без имени'}\n"
        f"Услуга: {service.name if service else 'Неизвестно'}\n"
        f"Дата: {format_date(appointment.appointment_date)}\n"
        f"Время: {format_datetime(appointment.appointment_date, '%H:%M')}\n"
        f"Стоимость: {appointment.total_price:.0f} ₽\n"
    )
    if getattr(appointment, 'master_id', None):
        master_row = await db.fetchrow("SELECT name FROM masters WHERE id = $1",
                                       appointment.master_id)
        if master_row:
            message += f"Мастер: {master_row['name']}\n"
    elif appointment.client_note:
        message += f"Желаемый мастер: {appointment.client_note}\n"
    message += "\n"
    
    # Всегда требуется подтверждение администратора
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"admin_confirm_{appointment.id}"),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin_reject_{appointment.id}")
        ]
    ])
    message += "⚠️ Требуется подтверждение:"
    
    try:
        await bot.send_message(ADMIN_ID, message, reply_markup=keyboard, parse_mode='HTML')
    except Exception as e:
        print(f"Ошибка отправки уведомления мастеру: {e}")

async def notify_master_appointment_changed(appointment: Appointment, change_type: str, bot: Bot):
    """Уведомить мастера об изменении записи"""
    service = await ServiceService.get_service(appointment.service_id)
    client_user = await db.fetchrow(
        "SELECT * FROM users WHERE id = $1",
        appointment.client_id
    )
    
    change_types = {
        'edited': '✏️ Запись изменена',
        'cancelled': '❌ Запись отменена'
    }
    
    message = (
        f"{change_types.get(change_type, '🔔 Изменение записи')}\n\n"
        f"Клиент: {client_user['full_name'] or client_user['username'] or 'Без имени'}\n"
        f"Услуга: {service.name if service else 'Неизвестно'}\n"
        f"Дата: {format_date(appointment.appointment_date)}\n"
        f"Время: {format_datetime(appointment.appointment_date, '%H:%M')}\n"
        f"Стоимость: {appointment.total_price:.0f} ₽\n"
    )
    
    if change_type == 'edited':
        message += "\n⚠️ Требуется проверить и подтвердить новую запись"
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"admin_confirm_{appointment.id}"),
                InlineKeyboardButton(text="❌ Отклонить", callback_data=f"admin_reject_{appointment.id}")
            ]
        ])
    else:
        keyboard = None
    
    try:
        await bot.send_message(ADMIN_ID, message, reply_markup=keyboard, parse_mode='HTML')
    except Exception as e:
        print(f"Ошибка отправки уведомления мастеру: {e}")


