"""Обработчики для клиентов"""
from aiogram import Router, F
from aiogram.types import (Message, CallbackQuery, InlineKeyboardMarkup,
                           InlineKeyboardButton, ReplyKeyboardMarkup,
                           KeyboardButton, ReplyKeyboardRemove)
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, date, time, timedelta
from typing import List, Optional
import re

from services.user_service import UserService
from services.service_service import ServiceService
from services.schedule_service import ScheduleService
from services.appointment_service import AppointmentService
from services.info_service import InfoService
from services.bot_settings_service import BotSettingsService
from utils.timezone import format_datetime, format_date, get_current_datetime_in_master_tz
from database import db

router = Router()

class BookingStates(StatesGroup):
    """Состояния для процесса записи"""
    selecting_department = State()
    selecting_service = State()
    selecting_date = State()
    selecting_time = State()
    selecting_master = State()
    entering_time = State()
    entering_master = State()
    selecting_additional_services = State()
    editing_appointment = State()
    editing_appointment_date = State()
    editing_appointment_time_entry = State()
    editing_appointment_time_slot = State()
    editing_appointment_confirm = State()
    editing_appointment_service = State()
    waiting_for_confirmation = State()


def _parse_time(text: str) -> Optional[time]:
    """Парсит время из текста: 14:30 / 14.30 / 1430 / 14 30 / 14"""
    text = text.strip().replace(" ", "").replace(".", ":").replace("-", ":")
    m = re.match(r'^(\d{1,2}):(\d{2})$', text)
    if m:
        h, mn = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mn <= 59:
            return time(h, mn)
    m = re.match(r'^(\d{3,4})$', text)
    if m:
        s = text.zfill(4)
        h, mn = int(s[:2]), int(s[2:])
        if 0 <= h <= 23 and 0 <= mn <= 59:
            return time(h, mn)
    m = re.match(r'^(\d{1,2})$', text)
    if m:
        h = int(m.group(1))
        if 0 <= h <= 23:
            return time(h, 0)
    return None

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    # Получаем или создаем пользователя
    user = await UserService.get_or_create_user(
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name
    )
    
    # Проверяем черный список
    if await UserService.is_blacklisted(message.from_user.id):
        await message.answer("❌ Доступ ограничен")
        return
    
    # Сбрасываем состояние
    await state.clear()
    
    # Получаем приветственное сообщение (можно кастомизировать через настройки)
    welcome_text = await BotSettingsService.get_setting(
        'welcome_message',
        '👋 Добро пожаловать! Я помогу вам записаться на услугу.'
    )
    
    # Главное меню
    phone = await UserService.get_phone(message.from_user.id)
    contact_btn_text = "📱 Мой номер сохранён ✅" if phone else "📱 Поделиться контактом"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Записаться", callback_data="book_service")],
        [InlineKeyboardButton(text="📋 Мои записи", callback_data="my_appointments")],
        [InlineKeyboardButton(text="ℹ️ Информация", callback_data="info")],
        [InlineKeyboardButton(text="❓ Частые вопросы", callback_data="faq")],
        [InlineKeyboardButton(text="📞 Связаться с администратором", callback_data="contact_master")],
        [InlineKeyboardButton(text=contact_btn_text, callback_data="share_contact")],
    ])

    await message.answer(welcome_text, reply_markup=keyboard)

@router.callback_query(F.data == "book_service")
async def show_departments(callback: CallbackQuery, state: FSMContext):
    """Показать список отделов"""
    await state.clear()
    departments = await db.fetch(
        "SELECT * FROM departments WHERE is_active = TRUE ORDER BY order_index"
    )
    if not departments:
        await callback.answer("Отделы ещё не добавлены", show_alert=True)
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=d['name'], callback_data=f"select_dept_{d['id']}")]
        for d in departments
    ] + [[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_start")]])

    await callback.message.edit_text("Выберите отдел:", reply_markup=keyboard)
    await state.set_state(BookingStates.selecting_department)


@router.callback_query(F.data.startswith("select_dept_"),
                       StateFilter(BookingStates.selecting_department))
async def select_department(callback: CallbackQuery, state: FSMContext):
    """Выбор отдела → показать услуги этого отдела"""
    dept_id = int(callback.data.split("_")[-1])
    dept = await db.fetchrow("SELECT name FROM departments WHERE id = $1", dept_id)
    await state.update_data(department_id=dept_id)

    services = await db.fetch("""
        SELECT * FROM services
        WHERE department_id = $1 AND is_active = TRUE AND is_additional = FALSE
        ORDER BY order_index, id
    """, dept_id)

    if not services:
        await callback.answer("В этом отделе пока нет услуг", show_alert=True)
        return

    # Группируем услуги по категории (подкатегории внутри отдела)
    from collections import OrderedDict
    grouped: dict = OrderedDict()
    for s in services:
        cat = s['category'] or ''
        grouped.setdefault(cat, []).append(s)

    buttons = []
    for cat, cat_services in grouped.items():
        if cat:
            # Разделитель-заголовок категории (некликабельный)
            buttons.append([
                InlineKeyboardButton(text=f"── {cat} ──", callback_data="ignore")
            ])
        for s in cat_services:
            desc = f" ({s['description']})" if s.get('description') else ""
            price_text = f"{s['price']:.0f} ₽{desc}"
            buttons.append([
                InlineKeyboardButton(
                    text=f"{s['name']} — {price_text}",
                    callback_data=f"select_service_{s['id']}"
                )
            ])
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="book_service")])

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await callback.message.edit_text(
        f"<b>{dept['name']}</b>\n\nВыберите услугу:",
        reply_markup=keyboard, parse_mode="HTML"
    )
    await state.set_state(BookingStates.selecting_service)

@router.callback_query(F.data.startswith("select_service_"))
async def select_service(callback: CallbackQuery, state: FSMContext):
    """Выбрать услугу и показать выбор дополнительных услуг"""
    service_id = int(callback.data.split("_")[-1])
    service = await ServiceService.get_service(service_id)
    
    if not service:
        await callback.answer("Услуга не найдена", show_alert=True)
        return
    
    # Сохраняем выбранную услугу в состояние
    await state.update_data(service_id=service_id, selected_additional_services=[])
    
    # Получаем доступные дополнительные услуги для этой основной услуги
    additional_services = await db.fetch("""
        SELECT s.* 
        FROM services s
        LEFT JOIN services_additional_links sal ON s.id = sal.additional_service_id
        WHERE s.is_active = TRUE 
        AND s.is_additional = TRUE
        AND (sal.main_service_id = $1 OR sal.main_service_id IS NULL)
    """, service_id)
    
    # Формируем информацию об услуге
    service_info = (
        f"<b>{service.name}</b>\n\n"
        f"💵 Цена: {service.price:.0f} ₽\n"
        f"⏱ Длительность: {service.duration_minutes} минут\n"
    )
    
    if service.description:
        service_info += f"\n{service.description}\n"
    
    data = await state.get_data()
    dept_id = data.get('department_id')

    if additional_services:
        service_info += "\n\nВыберите дополнительные услуги (необязательно):"
        keyboard_buttons = []
        for add_service in additional_services:
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=f"➕ {add_service['name']} (+{add_service['price']:.0f} ₽)",
                    callback_data=f"add_additional_service_{add_service['id']}"
                )
            ])
        keyboard_buttons.append([
            InlineKeyboardButton(text="✅ Перейти к выбору даты", callback_data="continue_to_date")
        ])
        keyboard_buttons.append([
            InlineKeyboardButton(text="🔙 Назад", callback_data="book_service")
        ])
        keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
        await callback.message.edit_text(service_info, reply_markup=keyboard, parse_mode='HTML')
        await state.set_state(BookingStates.selecting_additional_services)
    else:
        service_info += "\nВыберите дату:"
        current_date = get_current_datetime_in_master_tz()
        keyboard = await _generate_calendar(current_date.year, current_date.month,
                                            department_id=dept_id, service_id=service_id)
        await callback.message.edit_text(service_info, reply_markup=keyboard, parse_mode='HTML')
        await state.set_state(BookingStates.selecting_date)

async def _generate_calendar(year: int, month: int, admin_mode: bool = False,
                             department_id: Optional[int] = None,
                             service_id: Optional[int] = None) -> InlineKeyboardMarkup:
    """Генерация календаря для выбора даты"""
    import calendar
    
    keyboard_buttons = []
    
    # Заголовок с месяцем и годом
    month_names = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                   'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
    header = f"{month_names[month-1]} {year}"
    
    if admin_mode:
        prev_callback = f"admin_calendar_prev_{year}_{month}"
        next_callback = f"admin_calendar_next_{year}_{month}"
    else:
        prev_callback = f"calendar_prev_{year}_{month}"
        next_callback = f"calendar_next_{year}_{month}"
    
    keyboard_buttons.append([
        InlineKeyboardButton(text="◀️", callback_data=prev_callback),
        InlineKeyboardButton(text=header, callback_data="calendar_header"),
        InlineKeyboardButton(text="▶️", callback_data=next_callback)
    ])
    
    # Дни недели
    weekdays = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс']
    keyboard_buttons.append([
        InlineKeyboardButton(text=day, callback_data="calendar_weekday")
        for day in weekdays
    ])
    
    # Календарь
    cal = calendar.monthcalendar(year, month)
    today = get_current_datetime_in_master_tz().date()
    
    for week in cal:
        week_buttons = []
        for day in week:
            if day == 0:
                week_buttons.append(InlineKeyboardButton(text=" ", callback_data="calendar_empty"))
            else:
                day_date = date(year, month, day)
                if admin_mode:
                    # В режиме админа скрываем прошедшие даты
                    if day_date < today:
                        week_buttons.append(InlineKeyboardButton(text=" ", callback_data="calendar_empty"))
                    else:
                        # В режиме админа проверяем, можно ли настроить дату
                        schedule = await ScheduleService.get_schedule_for_date(day_date)
                        is_fully_booked = await ScheduleService.is_date_fully_booked(day_date)
                        
                        # Скрываем полностью занятые дни и выходные
                        if schedule and schedule.is_day_off:
                            week_buttons.append(InlineKeyboardButton(text=" ", callback_data="calendar_empty"))
                        elif is_fully_booked and schedule and not schedule.is_day_off:
                            week_buttons.append(InlineKeyboardButton(text=" ", callback_data="calendar_empty"))
                        else:
                            # Показываем дату как доступную для настройки
                            week_buttons.append(InlineKeyboardButton(
                                text=str(day),
                                callback_data=f"admin_schedule_date_{year}-{month:02d}-{day:02d}"
                            ))
                else:
                    # Для клиентов скрываем прошедшие даты
                    if day_date < today:
                        week_buttons.append(InlineKeyboardButton(text=" ", callback_data="calendar_past"))
                    else:
                        # Проверяем наличие работающих мастеров в отделе
                        if department_id:
                            working = await ScheduleService.get_working_masters(department_id, day_date,
                                                                                service_id=service_id)
                            if working:
                                week_buttons.append(InlineKeyboardButton(
                                    text=str(day),
                                    callback_data=f"calendar_date_{year}_{month}_{day}"
                                ))
                            else:
                                week_buttons.append(InlineKeyboardButton(text=" ", callback_data="calendar_empty"))
                        else:
                            # Без отдела — показываем все даты
                            week_buttons.append(InlineKeyboardButton(
                                text=str(day),
                                callback_data=f"calendar_date_{year}_{month}_{day}"
                            ))
        keyboard_buttons.append(week_buttons)
    
    if admin_mode:
        keyboard_buttons.append([
            InlineKeyboardButton(text="🔙 Назад", callback_data="admin_schedule")
        ])
    else:
        keyboard_buttons.append([
            InlineKeyboardButton(text="🔙 Назад", callback_data="book_service")
        ])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)

async def _generate_calendar_admin(year: int, month: int) -> InlineKeyboardMarkup:
    """Генерация календаря для админа"""
    return await _generate_calendar(year, month, admin_mode=True)


@router.callback_query(F.data.startswith("select_master_"),
                       StateFilter(BookingStates.selecting_master))
async def select_master(callback: CallbackQuery, state: FSMContext):
    """Клиент выбрал мастера → показываем доступные слоты"""
    master_id = int(callback.data.split("_")[-1])
    master = await db.fetchrow("SELECT * FROM masters WHERE id = $1", master_id)
    if not master:
        await callback.answer("Мастер не найден", show_alert=True)
        return

    await state.update_data(master_id=master_id, master_name=master['name'])

    st = await state.get_data()
    selected_date = date.fromisoformat(st['selected_date'])
    service_id = st.get('service_id')
    service = await ServiceService.get_service(service_id) if service_id else None
    duration = service.duration_minutes if service else 30

    slots = await ScheduleService.get_master_available_slots(master_id, selected_date, duration)

    if not slots:
        await callback.answer("На эту дату свободных слотов нет", show_alert=True)
        return

    # Кнопки в 2 столбца
    slot_buttons = [
        InlineKeyboardButton(
            text=s.strftime("%H:%M"),
            callback_data=f"pick_slot_{s.strftime('%H:%M')}"
        )
        for s in slots
    ]
    rows = [slot_buttons[i:i+2] for i in range(0, len(slot_buttons), 2)]
    rows.append([InlineKeyboardButton(text="🔙 Назад к выбору мастера", callback_data="back_to_masters")])

    await callback.message.edit_text(
        f"👤 Мастер: <b>{master['name']}</b>\n"
        f"📅 Дата: <b>{selected_date.strftime('%d.%m.%Y')}</b>\n\n"
        f"⏰ Выберите удобное время:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )
    await state.set_state(BookingStates.selecting_time)


@router.callback_query(F.data == "back_to_time_slots")
async def back_to_time_slots(callback: CallbackQuery, state: FSMContext):
    """Вернуться к выбору слота времени для текущего мастера"""
    st = await state.get_data()
    master_id = st.get('master_id')
    selected_date = date.fromisoformat(st['selected_date'])
    service_id = st.get('service_id')
    service = await ServiceService.get_service(service_id) if service_id else None
    duration = service.duration_minutes if service else 30

    master = await db.fetchrow("SELECT * FROM masters WHERE id = $1", master_id)
    if not master:
        await callback.answer("Мастер не найден", show_alert=True)
        return

    slots = await ScheduleService.get_master_available_slots(master_id, selected_date, duration)
    if not slots:
        await callback.answer("Свободных слотов больше нет", show_alert=True)
        return

    slot_buttons = [
        InlineKeyboardButton(
            text=s.strftime("%H:%M"),
            callback_data=f"pick_slot_{s.strftime('%H:%M')}"
        )
        for s in slots
    ]
    rows = [slot_buttons[i:i+2] for i in range(0, len(slot_buttons), 2)]
    rows.append([InlineKeyboardButton(text="🔙 Назад к выбору мастера", callback_data="back_to_masters")])

    await callback.message.edit_text(
        f"👤 Мастер: <b>{master['name']}</b>\n"
        f"📅 Дата: <b>{selected_date.strftime('%d.%m.%Y')}</b>\n\n"
        f"⏰ Выберите удобное время:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )
    await state.set_state(BookingStates.selecting_time)
    await callback.answer()


@router.callback_query(F.data == "back_to_masters")
async def back_to_masters(callback: CallbackQuery, state: FSMContext):
    """Вернуться к выбору мастера"""
    st = await state.get_data()
    dept_id = st.get('department_id')
    selected_date = date.fromisoformat(st['selected_date'])
    working = await ScheduleService.get_working_masters(dept_id, selected_date,
                                                        service_id=st.get('service_id')) if dept_id else []

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"👤 {m['name']}", callback_data=f"select_master_{m['id']}")]
        for m in working
    ] + [[InlineKeyboardButton(text="🔙 Назад к календарю", callback_data="back_to_calendar")]])

    await callback.message.edit_text(
        f"📅 <b>{selected_date.strftime('%d.%m.%Y')}</b>\n\nВыберите мастера:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await state.set_state(BookingStates.selecting_master)


@router.callback_query(F.data == "back_to_calendar")
async def back_to_calendar(callback: CallbackQuery, state: FSMContext):
    """Вернуться к календарю"""
    data = await state.get_data()
    current_date = get_current_datetime_in_master_tz()
    keyboard = await _generate_calendar(current_date.year, current_date.month,
                                        department_id=data.get('department_id'),
                                        service_id=data.get('service_id'))
    await callback.message.edit_text("Выберите дату:", reply_markup=keyboard)
    await state.set_state(BookingStates.selecting_date)


@router.message(StateFilter(BookingStates.entering_time))
async def handle_time_input(message: Message, state: FSMContext):
    """Клиент вводит время в чат"""
    parsed = _parse_time(message.text or "")
    if not parsed:
        await message.answer(
            "Не могу распознать время. Введите в формате <b>ЧЧ:ММ</b>, например: <b>14:30</b>",
            parse_mode="HTML",
        )
        return

    data = await state.get_data()
    selected_date = date.fromisoformat(data['selected_date'])
    master_id = data.get('master_id')
    service_id = data.get('service_id')
    service = await ServiceService.get_service(service_id) if service_id else None
    duration = service.duration_minutes if service else 30

    # Проверяем расписание мастера
    if master_id:
        sched = await ScheduleService.get_master_schedule(master_id, selected_date)
    else:
        sched = await ScheduleService.get_schedule_for_date(selected_date)

    if sched.is_day_off:
        await message.answer("Этот день — выходной. Вернитесь и выберите другую дату.")
        return

    if parsed < sched.start_time or parsed >= sched.end_time:
        await message.answer(
            f"Время должно быть с {sched.start_time.strftime('%H:%M')} "
            f"до {sched.end_time.strftime('%H:%M')}. Введите ещё раз:"
        )
        return

    # Проверяем что мастер не занят в это время
    if master_id:
        appt_dt = datetime.combine(selected_date, parsed)
        available = await ScheduleService.is_master_available(master_id, appt_dt, duration)
        if not available:
            await message.answer(
                "⚠️ Мастер уже занят в это время. Введите другое время:"
            )
            return

    await state.update_data(appointment_time=parsed.strftime("%H:%M"))
    await _show_booking_confirmation(message, state)


@router.message(StateFilter(BookingStates.entering_master))
async def handle_master_input(message: Message, state: FSMContext):
    """Клиент вводит имя мастера"""
    await state.update_data(master_name=message.text.strip())
    await _show_booking_confirmation(message, state)


@router.callback_query(F.data == "skip_master")
async def skip_master_callback(callback: CallbackQuery, state: FSMContext):
    """Пропустить выбор мастера"""
    await state.update_data(master_name=None)
    await callback.message.delete()
    await _show_booking_confirmation(callback.message, state)
    await callback.answer()


async def _show_booking_confirmation(message: Message, state: FSMContext):
    """Показать экран подтверждения записи"""
    data = await state.get_data()
    service_id = data.get('service_id')
    selected_date_str = data.get('selected_date')
    appointment_time = data.get('appointment_time')
    master_name = data.get('master_name')
    selected_additional = data.get('selected_additional_services', [])

    service = await ServiceService.get_service(service_id)
    if not service or not selected_date_str or not appointment_time:
        await message.answer("Ошибка: данные записи утеряны. Начните заново через /start")
        await state.clear()
        return

    total_price = service.price
    total_duration = service.duration_minutes

    text = (
        f"📋 <b>Подтверждение записи</b>\n\n"
        f"<b>Услуга:</b> {service.name}\n"
    )

    if selected_additional:
        text += "\n<b>Дополнительные услуги:</b>\n"
        for add_id in selected_additional:
            add_svc = await ServiceService.get_service(add_id)
            if add_svc:
                text += f"  ➕ {add_svc.name} — {add_svc.price:.0f} ₽\n"
                total_price += add_svc.price
                total_duration += add_svc.duration_minutes

    text += (
        f"\nДата: {date.fromisoformat(selected_date_str).strftime('%d.%m.%Y')}\n"
        f"Время: {appointment_time}\n"
        f"Длительность: {total_duration} мин\n"
        f"<b>Стоимость: {total_price:.0f} ₽</b>\n"
    )

    master_name = data.get('master_name')
    if master_name:
        text += f"👤 Мастер: {master_name}\n"

    text += "\nПодтвердите запись:"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_booking_final")],
        [InlineKeyboardButton(text="🔙 Изменить время", callback_data="back_to_time_slots")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="book_service")],
    ])
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(BookingStates.waiting_for_confirmation)


@router.callback_query(F.data.startswith("calendar_"))
async def handle_calendar(callback: CallbackQuery, state: FSMContext):
    """Обработка действий с календарем"""
    data = callback.data
    current_state = await state.get_state()

    # ── Режим редактирования даты/времени клиентом ──────────────────────────
    if current_state == BookingStates.editing_appointment_date.state:
        if data.startswith("calendar_date_"):
            # Делегируем в специализированный обработчик редактирования
            await edit_appointment_select_date(callback, state)
        elif data.startswith("calendar_prev_") or data.startswith("calendar_next_"):
            _, _, year, month = data.split("_")
            year, month = int(year), int(month)
            if data.startswith("calendar_prev_"):
                month = 12 if month == 1 else month - 1
                year = year - 1 if month == 12 else year
            else:
                month = 1 if month == 12 else month + 1
                year = year + 1 if month == 1 else year
            # Генерируем календарь без фильтрации по мастерам
            keyboard = await _generate_calendar(year, month)
            await callback.message.edit_reply_markup(reply_markup=keyboard)
        else:
            await callback.answer()
        return
    # ────────────────────────────────────────────────────────────────────────

    if data.startswith("calendar_date_"):
        # Выбрана дата — показываем работающих мастеров отдела
        _, _, year, month, day = data.split("_")
        selected_date = date(int(year), int(month), int(day))
        await state.update_data(selected_date=selected_date.isoformat())

        st = await state.get_data()
        dept_id = st.get('department_id')
        working = await ScheduleService.get_working_masters(dept_id, selected_date,
                                                            service_id=st.get('service_id')) if dept_id else []

        if not working:
            await callback.answer("В этот день нет доступных мастеров", show_alert=True)
            return

        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"👤 {m['name']}", callback_data=f"select_master_{m['id']}")]
            for m in working
        ] + [[InlineKeyboardButton(text="🔙 Назад к календарю", callback_data="back_to_calendar")]])

        await callback.message.edit_text(
            f"📅 <b>{selected_date.strftime('%d.%m.%Y')}</b>\n\nВыберите мастера:",
            reply_markup=keyboard,
            parse_mode="HTML",
        )
        await state.set_state(BookingStates.selecting_master)

    elif data.startswith("calendar_prev_"):
        _, _, year, month = data.split("_")
        year, month = int(year), int(month)
        month = 12 if month == 1 else month - 1
        year = year - 1 if month == 12 else year
        st = await state.get_data()
        keyboard = await _generate_calendar(year, month, department_id=st.get('department_id'),
                                            service_id=st.get('service_id'))
        await callback.message.edit_reply_markup(reply_markup=keyboard)

    elif data.startswith("calendar_next_"):
        _, _, year, month = data.split("_")
        year, month = int(year), int(month)
        month = 1 if month == 12 else month + 1
        year = year + 1 if month == 1 else year
        st = await state.get_data()
        keyboard = await _generate_calendar(year, month, department_id=st.get('department_id'),
                                            service_id=st.get('service_id'))
        await callback.message.edit_reply_markup(reply_markup=keyboard)

    else:
        await callback.answer()

@router.callback_query(F.data.startswith("pick_slot_"), StateFilter(BookingStates.selecting_time))
async def pick_slot(callback: CallbackQuery, state: FSMContext):
    """Клиент выбрал время из списка слотов"""
    time_str = callback.data.replace("pick_slot_", "")   # "HH:MM"
    await state.update_data(appointment_time=time_str)
    await _show_booking_confirmation(callback.message, state)
    await callback.answer()


@router.callback_query(F.data.startswith("select_time_"), StateFilter(BookingStates.selecting_time))
async def confirm_booking(callback: CallbackQuery, state: FSMContext):
    """Подтверждение записи"""
    time_str = callback.data.replace("select_time_", "")
    appointment_datetime = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
    
    data = await state.get_data()
    service_id = data.get('service_id')
    
    if not service_id:
        await callback.answer("Ошибка: услуга не выбрана", show_alert=True)
        return
    
    service = await ServiceService.get_service(service_id)
    if not service:
        await callback.answer("Услуга не найдена", show_alert=True)
        return
    
    # Проверяем доступность времени
    if not await ScheduleService.is_date_available(appointment_datetime, service.duration_minutes):
        await callback.answer("Это время уже занято", show_alert=True)
        return
    
    # Сохраняем выбранное время
    await state.update_data(appointment_datetime=time_str)
    
    # Формируем информацию о записи с учетом дополнительных услуг
    data = await state.get_data()
    selected_additional = data.get('selected_additional_services', [])
    
    total_price = service.price
    total_duration = service.duration_minutes
    
    booking_info = (
        f"📋 <b>Подтверждение записи</b>\n\n"
        f"<b>Основная услуга:</b> {service.name}\n"
    )
    
    if selected_additional:
        booking_info += "\n<b>Дополнительные услуги:</b>\n"
        for add_id in selected_additional:
            add_service = await ServiceService.get_service(add_id)
            if add_service:
                booking_info += f"  ➕ {add_service.name} - {add_service.price:.0f} ₽\n"
                total_price += add_service.price
                total_duration += add_service.duration_minutes
    
    booking_info += (
        f"\nДата: {format_date(appointment_datetime)}\n"
        f"Время: {format_datetime(appointment_datetime, '%H:%M')}\n"
        f"Длительность: {total_duration} минут\n"
        f"<b>Стоимость: {total_price:.0f} ₽</b>\n\n"
        f"Подтвердите запись:"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_booking_final")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="book_service")]
    ])
    
    await callback.message.edit_text(booking_info, reply_markup=keyboard, parse_mode='HTML')
    await state.set_state(BookingStates.waiting_for_confirmation)

@router.callback_query(F.data.startswith("add_additional_service_"), StateFilter(BookingStates.selecting_additional_services))
async def add_additional_service(callback: CallbackQuery, state: FSMContext):
    """Добавление дополнительной услуги"""
    additional_service_id = int(callback.data.split("_")[-1])
    data = await state.get_data()
    
    selected_additional = data.get('selected_additional_services', [])
    if additional_service_id not in selected_additional:
        selected_additional.append(additional_service_id)
        await state.update_data(selected_additional_services=selected_additional)
        await callback.answer(f"✅ Услуга добавлена!")
    else:
        # Удаляем если уже добавлена
        selected_additional.remove(additional_service_id)
        await state.update_data(selected_additional_services=selected_additional)
        await callback.answer(f"❌ Услуга удалена!")
    
    # Обновляем интерфейс
    service_id = data.get('service_id')
    service = await ServiceService.get_service(service_id)
    
    additional_services = await db.fetch("""
        SELECT s.* 
        FROM services s
        LEFT JOIN services_additional_links sal ON s.id = sal.additional_service_id
        WHERE s.is_active = TRUE 
        AND s.is_additional = TRUE
        AND (sal.main_service_id = $1 OR sal.main_service_id IS NULL)
    """, service_id)
    
    total_price = service.price
    text = (
        f"<b>{service.name}</b>\n\n"
        f"💵 Цена: {service.price:.0f} ₽\n"
        f"⏱ Длительность: {service.duration_minutes} минут\n"
    )
    
    if service.description:
        text += f"\n{service.description}\n"
    
    text += "\n\nВыберите дополнительные услуги (необязательно):"
    
    if selected_additional:
        text += "\n\n<b>Выбрано:</b>\n"
        for add_id in selected_additional:
            add_service = await ServiceService.get_service(add_id)
            if add_service:
                text += f"  ✅ {add_service.name} - {add_service.price:.0f} ₽\n"
                total_price += add_service.price
        text += f"\n<b>Итого: {total_price:.0f} ₽</b>"
    
    keyboard_buttons = []
    for add_service in additional_services:
        is_selected = "✅" if add_service['id'] in selected_additional else "➕"
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=f"{is_selected} {add_service['name']} (+{add_service['price']:.0f} ₽)",
                callback_data=f"add_additional_service_{add_service['id']}"
            )
        ])
    
    keyboard_buttons.append([
        InlineKeyboardButton(text="✅ Перейти к выбору даты", callback_data="continue_to_date")
    ])
    keyboard_buttons.append([
        InlineKeyboardButton(text="🔙 Назад", callback_data="book_service")
    ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')


@router.callback_query(F.data == "continue_to_date", StateFilter(BookingStates.selecting_additional_services))
async def continue_to_date(callback: CallbackQuery, state: FSMContext):
    """Перейти к выбору даты после выбора дополнительных услуг"""
    data = await state.get_data()
    service_id = data.get('service_id')
    service = await ServiceService.get_service(service_id)
    
    # Формируем информацию об услуге
    service_info = (
        f"<b>{service.name}</b>\n\n"
        f"💵 Цена: {service.price:.0f} ₽\n"
        f"⏱ Длительность: {service.duration_minutes} минут\n"
    )
    
    if service.description:
        service_info += f"\n{service.description}\n"
    
    # Показываем выбранные дополнительные услуги
    selected_additional = data.get('selected_additional_services', [])
    if selected_additional:
        service_info += "\n<b>Дополнительные услуги:</b>\n"
        total_price = service.price
        for add_id in selected_additional:
            add_service = await ServiceService.get_service(add_id)
            if add_service:
                service_info += f"  ➕ {add_service.name} - {add_service.price:.0f} ₽\n"
                total_price += add_service.price
        service_info += f"\n<b>Итого: {total_price:.0f} ₽</b>\n"
    
    service_info += "\nВыберите дату:"
    data = await state.get_data()
    current_date = get_current_datetime_in_master_tz()
    keyboard = await _generate_calendar(current_date.year, current_date.month,
                                        department_id=data.get('department_id'),
                                        service_id=data.get('service_id'))
    await callback.message.edit_text(service_info, reply_markup=keyboard, parse_mode='HTML')
    await state.set_state(BookingStates.selecting_date)

@router.callback_query(F.data == "confirm_booking_final", StateFilter(BookingStates.waiting_for_confirmation))
async def create_booking(callback: CallbackQuery, state: FSMContext):
    """Создание записи"""
    data = await state.get_data()
    service_id = data.get('service_id')

    # Поддержка старого (appointment_datetime) и нового (selected_date + appointment_time) формата
    if data.get('appointment_datetime'):
        appointment_datetime = datetime.strptime(data['appointment_datetime'], "%Y-%m-%d %H:%M")
    elif data.get('selected_date') and data.get('appointment_time'):
        d = date.fromisoformat(data['selected_date'])
        t = datetime.strptime(data['appointment_time'], "%H:%M").time()
        appointment_datetime = datetime.combine(d, t)
    else:
        await callback.answer("Ошибка при создании записи", show_alert=True)
        return

    if not service_id:
        await callback.answer("Ошибка при создании записи", show_alert=True)
        return

    master_name = data.get('master_name')
    
    # Получаем пользователя
    user = await UserService.get_or_create_user(
        telegram_id=callback.from_user.id,
        username=callback.from_user.username,
        full_name=callback.from_user.full_name
    )
    
    # Получаем ID клиента из таблицы clients
    client_row = await db.fetchrow("SELECT id FROM clients WHERE user_id = $1", user.id)
    if not client_row:
        # Создаем запись в clients
        client_id = await db.fetchval(
            "INSERT INTO clients (user_id) VALUES ($1) RETURNING id",
            user.id
        )
    else:
        client_id = client_row['id']
    
    # Получаем выбранные дополнительные услуги
    selected_additional = data.get('selected_additional_services', [])
    
    # Создаем запись
    try:
        master_id = data.get('master_id')
        appointment = await AppointmentService.create_appointment(
            client_id=user.id,
            service_id=service_id,
            appointment_date=appointment_datetime,
            additional_service_ids=selected_additional,
            master_id=master_id,
        )
        
        # Запись всегда ожидает подтверждения администратора
        await AppointmentService.update_appointment(appointment.id, status='pending')
        status_text = "⏳ Ожидает подтверждения администратора"
        
        # Создаем напоминания
        from services.reminder_service import ReminderService
        await ReminderService.schedule_reminders_for_appointment(appointment.id, appointment_datetime)
        
        # Формируем отчет для клиента
        service = await ServiceService.get_service(service_id)
        info_sections = await InfoService.get_all_info_sections()
        address_info = next((s for s in info_sections if s['key'] == 'address'), None)
        contacts_info = next((s for s in info_sections if s['key'] == 'contacts'), None)
        
        # Получаем дополнительные услуги из записи
        additional_services = await db.fetch("""
            SELECT s.name, s.price
            FROM appointment_additional_services aas
            JOIN services s ON aas.service_id = s.id
            WHERE aas.appointment_id = $1
        """, appointment.id)
        
        report = (
            f"⏳ <b>Запрос на запись отправлен!</b>\n\n"
            f"Услуга: {service.name}\n"
        )
        
        if additional_services:
            report += "\n<b>Дополнительные услуги:</b>\n"
            for add_service in additional_services:
                report += f"  ➕ {add_service['name']} - {add_service['price']:.0f} ₽\n"
        
        report += (
            f"\nДата: {format_date(appointment_datetime)}\n"
            f"Время: {format_datetime(appointment_datetime, '%H:%M')}\n"
            f"Длительность: {appointment.total_duration} минут\n"
            f"Стоимость: {appointment.total_price:.0f} ₽\n"
            f"Статус: {status_text}\n\n"
            f"Мы уведомим вас, когда администратор подтвердит запись."
        )

        if address_info and address_info.get('content'):
            report += f"\n\n📍 Адрес: {address_info['content']}"

        if contacts_info and contacts_info.get('content'):
            report += f"\n📞 Контакты: {contacts_info['content']}"

        await callback.message.edit_text(report, parse_mode='HTML')

        # Уведомляем администратора с кнопками подтверждения/отклонения
        from services.notification_service import notify_master_new_booking
        await notify_master_new_booking(appointment, callback.bot)

        await state.clear()
        await callback.answer("Запрос отправлен!")
        
    except Exception as e:
        await callback.answer(f"Ошибка: {str(e)}", show_alert=True)
        import logging
        logging.exception(f"Ошибка при создании записи: {e}")

@router.callback_query(F.data == "my_appointments")
async def show_my_appointments(callback: CallbackQuery):
    """Показать записи клиента"""
    user = await UserService.get_or_create_user(
        telegram_id=callback.from_user.id
    )
    
    appointments = await AppointmentService.get_client_appointments(user.id, only_active=True)
    
    if not appointments:
        await callback.message.edit_text("У вас нет активных записей")
        return
    
    text = "📋 <b>Ваши записи:</b>\n\n"
    
    keyboard_buttons = []
    for appointment in appointments:
        info = await AppointmentService.format_appointment_info(appointment)
        text += info + "\n\n"
        
        keyboard_buttons.append([
            InlineKeyboardButton(
                text=f"✏️ Редактировать запись #{appointment.id}",
                callback_data=f"edit_appointment_{appointment.id}"
            )
        ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons + [
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_start")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')

@router.callback_query(F.data.regexp(r"^edit_appointment_\d+$"))
async def edit_appointment(callback: CallbackQuery, state: FSMContext):
    """Редактирование записи"""
    appointment_id = int(callback.data.split("_")[-1])
    appointment = await AppointmentService.get_appointment(appointment_id)
    
    if not appointment:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    
    # Проверяем, что это запись текущего пользователя
    user = await UserService.get_or_create_user(telegram_id=callback.from_user.id)
    if appointment.client_id != user.id:
        await callback.answer("❌ Это не ваша запись", show_alert=True)
        return
    
    # Сохраняем ID записи
    await state.update_data(appointment_id=appointment_id)
    
    # Показываем текущую информацию о записи
    appointment_info = await AppointmentService.format_appointment_info(appointment)
    
    text = (
        f"✏️ <b>Редактирование записи #{appointment_id}</b>\n\n"
        f"{appointment_info}\n\n"
        f"⚠️ <i>Внимание: мастер проверит изменения и подтвердит их</i>\n\n"
        f"Что хотите изменить?"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Изменить дату/время", callback_data=f"edit_appointment_time_{appointment_id}")],
        [InlineKeyboardButton(text="🔧 Изменить услугу", callback_data=f"edit_appointment_service_{appointment_id}")],
        [InlineKeyboardButton(text="❌ Отменить запись", callback_data=f"cancel_appointment_{appointment_id}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="my_appointments")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')
    await state.set_state(BookingStates.editing_appointment)

@router.callback_query(F.data.startswith("edit_appointment_time_"), StateFilter(BookingStates.editing_appointment))
async def edit_appointment_time(callback: CallbackQuery, state: FSMContext):
    """Редактирование даты и времени записи клиентом"""
    appointment_id = int(callback.data.split("_")[-1])
    appointment = await AppointmentService.get_appointment(appointment_id)
    
    if not appointment:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    
    # Проверяем, что это запись текущего пользователя
    user = await UserService.get_or_create_user(telegram_id=callback.from_user.id)
    if appointment.client_id != user.id:
        await callback.answer("❌ Это не ваша запись", show_alert=True)
        return
    
    await state.update_data(appointment_id=appointment_id)
    
    text = (
        f"📅 <b>Изменение даты и времени записи #{appointment_id}</b>\n\n"
        f"Текущая дата и время: {format_datetime(appointment.appointment_date)}\n\n"
        f"Выберите новую дату:"
    )
    
    # Показываем календарь
    current_date = get_current_datetime_in_master_tz()
    keyboard = await _generate_calendar(current_date.year, current_date.month)
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')
    await state.set_state(BookingStates.editing_appointment_date)

@router.callback_query(F.data.startswith("calendar_date_"), StateFilter(BookingStates.editing_appointment_date))
async def edit_appointment_select_date(callback: CallbackQuery, state: FSMContext):
    """Выбор новой даты при редактировании — показываем слоты кнопками"""
    _, _, year, month, day = callback.data.split("_")
    selected_date = date(int(year), int(month), int(day))

    st = await state.get_data()
    appointment_id = st.get('appointment_id')

    # Получаем запись, чтобы знать мастера и длительность
    appointment = await AppointmentService.get_appointment(appointment_id)
    if not appointment:
        await callback.answer("Запись не найдена", show_alert=True)
        return

    master_id = appointment.master_id
    duration = appointment.total_duration or 60

    if master_id:
        slots = await ScheduleService.get_master_available_slots(master_id, selected_date, duration)
    else:
        # Нет закреплённого мастера — берём слоты по общему расписанию
        schedule = await ScheduleService.get_schedule_for_date(selected_date)
        if schedule.is_day_off or not schedule.start_time or not schedule.end_time:
            await callback.answer("Этот день — выходной", show_alert=True)
            return
        from datetime import timedelta as _td
        step = _td(minutes=30)
        cur = datetime.combine(selected_date, schedule.start_time)
        end_dt = datetime.combine(selected_date, schedule.end_time)
        slots = []
        from utils.timezone import get_current_datetime_in_master_tz
        now = get_current_datetime_in_master_tz().replace(tzinfo=None)
        while cur + _td(minutes=duration) <= end_dt:
            if selected_date == now.date() and cur <= now:
                cur += step
                continue
            slots.append(cur.time())
            cur += step

    if not slots:
        await callback.answer("На эту дату нет свободных слотов", show_alert=True)
        return

    await state.update_data(edit_selected_date=selected_date.isoformat())

    slot_buttons = [
        InlineKeyboardButton(
            text=s.strftime("%H:%M"),
            callback_data=f"edit_pick_slot_{s.strftime('%H:%M')}"
        )
        for s in slots
    ]
    rows = [slot_buttons[i:i + 2] for i in range(0, len(slot_buttons), 2)]
    rows.append([InlineKeyboardButton(text="🔙 Выбрать другую дату", callback_data="edit_back_to_calendar")])

    master_row = await db.fetchrow("SELECT name FROM masters WHERE id = $1", master_id) if master_id else None
    master_label = f"\n👤 Мастер: <b>{master_row['name']}</b>" if master_row else ""

    await callback.message.edit_text(
        f"📅 Дата: <b>{selected_date.strftime('%d.%m.%Y')}</b>{master_label}\n\n"
        f"⏰ Выберите удобное время:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode="HTML",
    )
    await state.set_state(BookingStates.editing_appointment_time_slot)
    await callback.answer()


@router.callback_query(F.data == "edit_back_to_calendar")
async def edit_back_to_calendar(callback: CallbackQuery, state: FSMContext):
    """Вернуться к календарю при редактировании даты"""
    current_date = get_current_datetime_in_master_tz()
    keyboard = await _generate_calendar(current_date.year, current_date.month)
    st = await state.get_data()
    appointment_id = st.get('appointment_id')
    await callback.message.edit_text(
        f"📅 <b>Изменение даты и времени записи #{appointment_id}</b>\n\nВыберите новую дату:",
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    await state.set_state(BookingStates.editing_appointment_date)
    await callback.answer()


@router.callback_query(F.data.startswith("edit_pick_slot_"), StateFilter(BookingStates.editing_appointment_time_slot))
async def edit_pick_slot(callback: CallbackQuery, state: FSMContext):
    """Клиент выбрал слот при редактировании → показываем подтверждение с двумя кнопками"""
    time_str = callback.data.replace("edit_pick_slot_", "")   # "HH:MM"
    st = await state.get_data()
    appointment_id = st.get('appointment_id')
    selected_date = date.fromisoformat(st['edit_selected_date'])

    appointment = await AppointmentService.get_appointment(appointment_id)
    service = await ServiceService.get_service(appointment.service_id) if appointment else None
    master_id = appointment.master_id if appointment else None
    master_row = await db.fetchrow("SELECT name FROM masters WHERE id = $1", master_id) if master_id else None

    await state.update_data(edit_selected_time=time_str)

    text = (
        f"✏️ <b>Подтверждение изменения</b>\n\n"
        f"Запись: #{appointment_id}\n"
        f"Услуга: {service.name if service else '—'}\n"
        f"📅 Новая дата: <b>{selected_date.strftime('%d.%m.%Y')}</b>\n"
        f"⏰ Новое время: <b>{time_str}</b>\n"
    )
    if master_row:
        text += f"👤 Мастер: {master_row['name']}\n"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="edit_confirm_time_change")],
        [InlineKeyboardButton(text="🔙 Изменить дату", callback_data="edit_back_to_calendar")],
    ])
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await state.set_state(BookingStates.editing_appointment_confirm)
    await callback.answer()


@router.callback_query(F.data == "edit_confirm_time_change", StateFilter(BookingStates.editing_appointment_confirm))
async def edit_confirm_time_change(callback: CallbackQuery, state: FSMContext):
    """Отправляем администратору запрос на подтверждение переноса"""
    from config import ADMIN_ID
    st = await state.get_data()
    appointment_id = st.get('appointment_id')
    selected_date = date.fromisoformat(st['edit_selected_date'])
    time_str = st.get('edit_selected_time')

    if not time_str:
        await callback.answer("Ошибка: время не выбрано", show_alert=True)
        return

    appointment = await AppointmentService.get_appointment(appointment_id)
    if not appointment:
        await callback.answer("Запись не найдена", show_alert=True)
        return

    service = await ServiceService.get_service(appointment.service_id)
    client_user = await db.fetchrow("SELECT * FROM users WHERE id = $1", appointment.client_id)
    master_row = await db.fetchrow("SELECT name FROM masters WHERE id = $1", appointment.master_id) \
        if appointment.master_id else None

    # Кодируем новую дату/время в callback_data: YYYYMMDD_HHMM
    dt_code = f"{selected_date.strftime('%Y%m%d')}_{time_str.replace(':', '')}"

    admin_text = (
        f"🔄 <b>Запрос на перенос записи</b>\n\n"
        f"Клиент: {client_user['full_name'] or client_user['username'] or 'Без имени'}\n"
        f"Услуга: {service.name if service else '—'}\n"
        f"Текущее время: <b>{format_datetime(appointment.appointment_date)}</b>\n"
        f"Новое время: <b>{selected_date.strftime('%d.%m.%Y')} {time_str}</b>\n"
    )
    if master_row:
        admin_text += f"Мастер: {master_row['name']}\n"
    admin_text += "\n⚠️ Требуется подтверждение:"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"admin_ok_dc_{appointment_id}_{dt_code}"),
        InlineKeyboardButton(text="❌ Отклонить",   callback_data=f"admin_no_dc_{appointment_id}"),
    ]])

    try:
        await callback.bot.send_message(ADMIN_ID, admin_text, reply_markup=keyboard, parse_mode="HTML")
    except Exception as e:
        await callback.answer(f"Не удалось отправить запрос: {e}", show_alert=True)
        return

    await callback.message.edit_text(
        "⏳ <b>Запрос на перенос отправлен!</b>\n\nОжидайте подтверждения администратора.",
        parse_mode="HTML",
        reply_markup=None,
    )
    await state.clear()
    await callback.answer()

@router.callback_query(F.data.startswith("edit_appointment_select_time_"))
async def edit_appointment_confirm_time(callback: CallbackQuery, state: FSMContext):
    """Подтверждение нового времени записи"""
    time_str = callback.data.replace("edit_appointment_select_time_", "")
    new_datetime = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
    
    data = await state.get_data()
    appointment_id = data.get('appointment_id')
    
    appointment = await AppointmentService.get_appointment(appointment_id)
    if not appointment:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    
    # Обновляем запись
    try:
        await AppointmentService.update_appointment(appointment_id, appointment_date=new_datetime)
        
        # Уведомляем мастера
        from services.notification_service import notify_master_appointment_changed
        await notify_master_appointment_changed(appointment, "date_changed", callback.bot)
        
        await callback.answer("✅ Запись обновлена! Мастер уведомлен.")
        await state.clear()
        
        # Возвращаемся к списку записей
        await show_my_appointments(callback)
    except Exception as e:
        await callback.answer(f"Ошибка: {str(e)}", show_alert=True)

@router.callback_query(
    F.data.startswith("edit_appointment_service_"),
    StateFilter(BookingStates.editing_appointment, BookingStates.editing_appointment_service)
)
async def edit_appointment_service(callback: CallbackQuery, state: FSMContext):
    """Редактирование услуги записи клиентом — шаг 1: выбор отдела"""
    appointment_id = int(callback.data.split("_")[-1])
    appointment = await AppointmentService.get_appointment(appointment_id)

    if not appointment:
        await callback.answer("Запись не найдена", show_alert=True)
        return

    user = await UserService.get_or_create_user(telegram_id=callback.from_user.id)
    if appointment.client_id != user.id:
        await callback.answer("❌ Это не ваша запись", show_alert=True)
        return

    departments = await db.fetch(
        "SELECT * FROM departments WHERE is_active = TRUE ORDER BY order_index"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=d['name'],
                              callback_data=f"edit_svc_dept_{appointment_id}_{d['id']}")]
        for d in departments
    ] + [[InlineKeyboardButton(text="🔙 Назад", callback_data=f"edit_appointment_{appointment_id}")]])

    await callback.message.edit_text(
        f"🔧 <b>Изменение услуги записи #{appointment_id}</b>\n\nВыберите отдел:",
        reply_markup=keyboard, parse_mode='HTML'
    )
    await state.set_state(BookingStates.editing_appointment_service)


@router.callback_query(F.data.startswith("edit_svc_dept_"), StateFilter(BookingStates.editing_appointment_service))
async def edit_appointment_service_dept(callback: CallbackQuery, state: FSMContext):
    """Редактирование услуги записи — шаг 2: услуги отдела, сгруппированные по категории"""
    _, _, _, appt_id_str, dept_id_str = callback.data.split("_")
    appointment_id = int(appt_id_str)
    dept_id = int(dept_id_str)

    dept = await db.fetchrow("SELECT name FROM departments WHERE id = $1", dept_id)
    services = await db.fetch("""
        SELECT * FROM services
        WHERE department_id = $1 AND is_active = TRUE AND is_additional = FALSE
        ORDER BY order_index, id
    """, dept_id)

    if not services:
        await callback.answer("В этом отделе пока нет услуг", show_alert=True)
        return

    from collections import OrderedDict
    grouped: dict = OrderedDict()
    for s in services:
        grouped.setdefault(s['category'] or '', []).append(s)

    buttons = []
    for cat, cat_services in grouped.items():
        if cat:
            buttons.append([InlineKeyboardButton(text=f"── {cat} ──", callback_data="ignore")])
        for s in cat_services:
            desc = f" ({s['description']})" if s.get('description') else ""
            buttons.append([InlineKeyboardButton(
                text=f"{s['name']} — {s['price']:.0f} ₽{desc}",
                callback_data=f"edit_appointment_set_service_{appointment_id}_{s['id']}"
            )])
    buttons.append([InlineKeyboardButton(
        text="🔙 Назад к отделам",
        callback_data=f"edit_appointment_service_{appointment_id}"
    )])

    await callback.message.edit_text(
        f"🔧 <b>{dept['name']}</b>\n\nВыберите новую услугу:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode='HTML'
    )
    await callback.answer()

@router.callback_query(F.data.startswith("edit_appointment_set_service_"))
async def edit_appointment_confirm_service(callback: CallbackQuery, state: FSMContext):
    """Подтверждение новой услуги записи"""
    parts = callback.data.split("_")
    appointment_id = int(parts[-2])
    service_id = int(parts[-1])
    
    appointment = await AppointmentService.get_appointment(appointment_id)
    if not appointment:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    
    # Проверяем, что это запись текущего пользователя
    user = await UserService.get_or_create_user(telegram_id=callback.from_user.id)
    if appointment.client_id != user.id:
        await callback.answer("❌ Это не ваша запись", show_alert=True)
        return
    
    try:
        await AppointmentService.update_appointment(appointment_id, service_id=service_id)
        
        # Уведомляем мастера
        from services.notification_service import notify_master_appointment_changed
        await notify_master_appointment_changed(appointment, "service_changed", callback.bot)
        
        await callback.answer("✅ Услуга обновлена! Мастер уведомлен.")
        await state.clear()
        
        # Возвращаемся к списку записей
        await show_my_appointments(callback)
    except Exception as e:
        await callback.answer(f"Ошибка: {str(e)}", show_alert=True)

@router.callback_query(F.data.startswith("cancel_appointment_"))
async def cancel_appointment(callback: CallbackQuery):
    """Отмена записи клиентом"""
    appointment_id = int(callback.data.split("_")[-1])
    appointment = await AppointmentService.get_appointment(appointment_id)
    
    if not appointment:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    
    # Проверяем, что это запись текущего пользователя
    user = await UserService.get_or_create_user(telegram_id=callback.from_user.id)
    if appointment.client_id != user.id:
        await callback.answer("❌ Это не ваша запись", show_alert=True)
        return
    
    try:
        await AppointmentService.update_appointment(appointment_id, status='cancelled')
        
        # Уведомляем мастера
        from services.notification_service import notify_master_appointment_changed
        await notify_master_appointment_changed(appointment, "cancelled", callback.bot)
        
        await callback.answer("✅ Запись отменена. Мастер уведомлен.")
        
        # Возвращаемся к списку записей
        await show_my_appointments(callback)
    except Exception as e:
        await callback.answer(f"Ошибка: {str(e)}", show_alert=True)

@router.callback_query(F.data == "info")
async def show_info(callback: CallbackQuery):
    """Показать информационные разделы"""
    sections = await InfoService.get_all_info_sections()
    
    if not sections:
        await callback.answer("Информация пока не добавлена", show_alert=True)
        return
    
    keyboard_buttons = []
    for section in sections:
        if section.get('content'):
            keyboard_buttons.append([
                InlineKeyboardButton(
                    text=section['title'],
                    callback_data=f"info_{section['key']}"
                )
            ])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=keyboard_buttons + [
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_start")]
    ])
    
    await callback.message.edit_text("ℹ️ <b>Информация</b>", reply_markup=keyboard, parse_mode='HTML')

@router.callback_query(F.data.startswith("info_"))
async def show_info_section(callback: CallbackQuery):
    """Показать конкретный информационный раздел"""
    section_key = callback.data.replace("info_", "")
    section = await InfoService.get_info_section(section_key)
    
    if not section or not section.get('content'):
        await callback.answer("Информация не найдена", show_alert=True)
        return
    
    text = f"<b>{section['title']}</b>\n\n{section['content']}"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="info")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')

@router.callback_query(F.data == "faq")
async def show_faq(callback: CallbackQuery):
    """Показать FAQ"""
    faq_list = await InfoService.get_faq()
    
    if not faq_list:
        await callback.answer("FAQ пока не добавлены", show_alert=True)
        return
    
    text = "❓ <b>Частые вопросы:</b>\n\n"
    
    for item in faq_list:
        text += f"<b>Q: {item['question']}</b>\n"
        text += f"A: {item['answer']}\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_start")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')

@router.callback_query(F.data == "contact_master")
async def contact_master(callback: CallbackQuery):
    """Связаться с администратором"""
    from config import ADMIN_ID
    
    text = (
        "📞 <b>Связаться с администратором</b>\n\n"
        "Вы можете написать администратору в личные сообщения или использовать кнопку ниже:"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Написать администратору", url=f"tg://user?id={ADMIN_ID}")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="back_to_start")]
    ])
    
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode='HTML')

@router.callback_query(F.data == "back_to_start")
async def back_to_start(callback: CallbackQuery, state: FSMContext):
    """Вернуться в главное меню"""
    await state.clear()
    
    # Получаем приветственное сообщение
    welcome_text = await BotSettingsService.get_setting(
        'welcome_message',
        '👋 Добро пожаловать! Я помогу вам записаться на услугу.'
    )
    
    phone = await UserService.get_phone(callback.from_user.id)
    contact_btn_text = "📱 Мой номер сохранён ✅" if phone else "📱 Поделиться контактом"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Записаться", callback_data="book_service")],
        [InlineKeyboardButton(text="📋 Мои записи", callback_data="my_appointments")],
        [InlineKeyboardButton(text="ℹ️ Информация", callback_data="info")],
        [InlineKeyboardButton(text="❓ Частые вопросы", callback_data="faq")],
        [InlineKeyboardButton(text="📞 Связаться с администратором", callback_data="contact_master")],
        [InlineKeyboardButton(text=contact_btn_text, callback_data="share_contact")],
    ])

    await callback.message.edit_text(welcome_text, reply_markup=keyboard)

@router.callback_query(F.data.startswith("confirm_attendance_"))
async def confirm_attendance(callback: CallbackQuery):
    """Подтверждение клиентом, что он придет"""
    appointment_id = int(callback.data.split("_")[-1])
    appointment = await AppointmentService.get_appointment(appointment_id)
    
    if not appointment:
        await callback.answer("Запись не найдена", show_alert=True)
        return
    
    # Уведомляем мастера
    from config import ADMIN_ID
    client_user = await db.fetchrow("SELECT full_name FROM users WHERE id = $1", appointment.client_id)
    client_name = client_user['full_name'] if client_user else "Клиент"
    
    try:
        await callback.bot.send_message(
            ADMIN_ID,
            f"✅ Клиент {client_name} подтвердил, что придет на запись {format_datetime(appointment.appointment_date)}"
        )
    except:
        pass
    
    await callback.answer("Спасибо! Мастер уведомлен.")
    await callback.message.edit_text(
        callback.message.text + "\n\n✅ Подтверждено! Мастер уведомлен."
    )

@router.callback_query(F.data == "share_contact")
async def request_contact(callback: CallbackQuery):
    """Запросить контакт клиента"""
    phone = await UserService.get_phone(callback.from_user.id)
    if phone:
        await callback.answer(f"Ваш номер уже сохранён: {phone}", show_alert=True)
        return

    keyboard = ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить мой номер", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
    await callback.message.answer(
        "Нажмите кнопку ниже, чтобы поделиться номером телефона.\n"
        "Это поможет мастеру связаться с вами при необходимости.",
        reply_markup=keyboard,
    )
    await callback.answer()

@router.message(F.contact)
async def handle_contact(message: Message):
    """Обработать полученный контакт"""
    if message.contact.user_id != message.from_user.id:
        await message.answer(
            "Пожалуйста, отправьте свой собственный контакт.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    phone = message.contact.phone_number
    await UserService.save_phone(message.from_user.id, phone)

    await message.answer(
        f"✅ Номер телефона <b>{phone}</b> сохранён!",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="HTML",
    )
