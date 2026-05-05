"""Управление мастерами и их расписанием — админ-панель"""
import calendar
from datetime import date, datetime, time, timedelta
from typing import Optional

from aiogram import Router, F
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database import db
from services.schedule_service import ScheduleService
from services.user_service import UserService
from utils.timezone import get_current_datetime_in_master_tz

router = Router()


# ──────────────────────────────────────────────
# Состояния
# ──────────────────────────────────────────────

class MasterAdminStates(StatesGroup):
    adding_name       = State()   # ввод имени при создании
    selecting_dept    = State()   # выбор отдела при создании
    editing_name      = State()   # ввод нового имени
    entering_hours    = State()   # ввод рабочих часов (формат "09:00-18:00")


# ──────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────

def _master_menu(master_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Изменить имя",    callback_data=f"adm_master_rename_{master_id}")],
        [InlineKeyboardButton(text="🏢 Изменить отдел",  callback_data=f"adm_master_dept_{master_id}")],
        [InlineKeyboardButton(text="📅 Расписание",      callback_data=f"adm_master_sched_{master_id}")],
        [InlineKeyboardButton(text="🔄 Вкл/Выкл",       callback_data=f"adm_master_toggle_{master_id}")],
        [InlineKeyboardButton(text="🗑 Удалить",         callback_data=f"adm_master_delete_{master_id}")],
        [InlineKeyboardButton(text="🔙 Назад",           callback_data="adm_masters")],
    ])


async def _masters_list_keyboard() -> InlineKeyboardMarkup:
    masters = await db.fetch("""
        SELECT m.*, d.name AS dept_name
        FROM masters m
        LEFT JOIN departments d ON m.department_id = d.id
        ORDER BY d.order_index, m.order_index, m.name
    """)
    buttons = []
    for m in masters:
        status = "✅" if m['is_active'] else "❌"
        dept = m['dept_name'] or "—"
        buttons.append([InlineKeyboardButton(
            text=f"{status} {m['name']} ({dept})",
            callback_data=f"adm_master_{m['id']}"
        )])
    buttons.append([InlineKeyboardButton(text="➕ Добавить мастера", callback_data="adm_master_add")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад в меню",     callback_data="admin_back")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _dept_keyboard(callback_prefix: str) -> InlineKeyboardMarkup:
    depts = await db.fetch("SELECT * FROM departments WHERE is_active=TRUE ORDER BY order_index")
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=d['name'], callback_data=f"{callback_prefix}{d['id']}")]
        for d in depts
    ] + [[InlineKeyboardButton(text="🔙 Назад", callback_data="adm_masters")]])


def _schedule_calendar(master_id: int, year: int, month: int) -> InlineKeyboardMarkup:
    """Простой календарь для выбора даты расписания мастера."""
    month_names = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь',
                   'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
    buttons = [
        [
            InlineKeyboardButton(text="◀️", callback_data=f"adm_sched_prev_{master_id}_{year}_{month}"),
            InlineKeyboardButton(text=f"{month_names[month-1]} {year}", callback_data="ignore"),
            InlineKeyboardButton(text="▶️", callback_data=f"adm_sched_next_{master_id}_{year}_{month}"),
        ],
        [InlineKeyboardButton(text=d, callback_data="ignore")
         for d in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]],
    ]
    today = date.today()
    for week in calendar.monthcalendar(year, month):
        row = []
        for day in week:
            if day == 0:
                row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
            else:
                d = date(year, month, day)
                marker = "📅" if d >= today else "·"
                row.append(InlineKeyboardButton(
                    text=f"{marker}{day}",
                    callback_data=f"adm_sched_date_{master_id}_{d.isoformat()}"
                ))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="🔙 Назад к мастеру",
                                         callback_data=f"adm_master_{master_id}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _parse_hours(text: str):
    """Парсит строку вида '9:00-18:00' или '9-18'. Возвращает (start_time, end_time) или None."""
    import re
    text = text.strip().replace(" ", "")
    m = re.match(r'^(\d{1,2}(?::\d{2})?)[–\-](\d{1,2}(?::\d{2})?)$', text)
    if not m:
        return None
    def to_time(s):
        if ':' in s:
            h, mn = map(int, s.split(':'))
        else:
            h, mn = int(s), 0
        if 0 <= h <= 23 and 0 <= mn <= 59:
            return time(h, mn)
        return None
    s, e = to_time(m.group(1)), to_time(m.group(2))
    if s and e and s < e:
        return s, e
    return None


# ──────────────────────────────────────────────
# Главный экран управления мастерами
# ──────────────────────────────────────────────

@router.callback_query(F.data == "adm_masters")
async def admin_masters(callback: CallbackQuery, state: FSMContext):
    if not await UserService.is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    await state.clear()
    keyboard = await _masters_list_keyboard()
    await callback.message.edit_text("👨‍💼 <b>Управление мастерами</b>", reply_markup=keyboard,
                                     parse_mode="HTML")


# ──────────────────────────────────────────────
# Карточка мастера
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_master_") &
                       ~F.data.startswith("adm_master_rename_") &
                       ~F.data.startswith("adm_master_dept_") &
                       ~F.data.startswith("adm_master_sched_") &
                       ~F.data.startswith("adm_master_toggle_") &
                       ~F.data.startswith("adm_master_delete_") &
                       ~F.data.startswith("adm_master_add"))
async def master_card(callback: CallbackQuery):
    if not await UserService.is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    master_id = int(callback.data.split("_")[-1])
    row = await db.fetchrow("""
        SELECT m.*, d.name AS dept_name FROM masters m
        LEFT JOIN departments d ON m.department_id = d.id
        WHERE m.id = $1
    """, master_id)
    if not row:
        return await callback.answer("Мастер не найден", show_alert=True)

    status = "✅ Активен" if row['is_active'] else "❌ Неактивен"
    text = (f"👤 <b>{row['name']}</b>\n"
            f"Отдел: {row['dept_name'] or '—'}\n"
            f"Статус: {status}")
    await callback.message.edit_text(text, reply_markup=_master_menu(master_id), parse_mode="HTML")


# ──────────────────────────────────────────────
# Добавление мастера
# ──────────────────────────────────────────────

@router.callback_query(F.data == "adm_master_add")
async def master_add_start(callback: CallbackQuery, state: FSMContext):
    if not await UserService.is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    await callback.message.edit_text("Введите имя нового мастера:")
    await state.set_state(MasterAdminStates.adding_name)


@router.message(StateFilter(MasterAdminStates.adding_name))
async def master_add_name(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        return await message.answer("Имя не может быть пустым. Введите ещё раз:")
    await state.update_data(new_master_name=name)
    keyboard = await _dept_keyboard("adm_master_dept_new_")
    await message.answer("Выберите отдел для мастера:", reply_markup=keyboard)
    await state.set_state(MasterAdminStates.selecting_dept)


@router.callback_query(F.data.startswith("adm_master_dept_new_"),
                       StateFilter(MasterAdminStates.selecting_dept))
async def master_add_dept(callback: CallbackQuery, state: FSMContext):
    dept_id = int(callback.data.split("_")[-1])
    data = await state.get_data()
    name = data.get("new_master_name", "")
    master_id = await db.fetchval(
        "INSERT INTO masters (name, department_id) VALUES ($1, $2) RETURNING id",
        name, dept_id
    )
    await state.clear()
    dept = await db.fetchrow("SELECT name FROM departments WHERE id = $1", dept_id)
    await callback.message.edit_text(
        f"✅ Мастер <b>{name}</b> ({dept['name']}) добавлен.",
        parse_mode="HTML",
        reply_markup=_master_menu(master_id)
    )


# ──────────────────────────────────────────────
# Переименование
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_master_rename_"))
async def master_rename_start(callback: CallbackQuery, state: FSMContext):
    if not await UserService.is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    master_id = int(callback.data.split("_")[-1])
    await state.update_data(editing_master_id=master_id)
    await callback.message.edit_text("Введите новое имя мастера:")
    await state.set_state(MasterAdminStates.editing_name)


@router.message(StateFilter(MasterAdminStates.editing_name))
async def master_rename_save(message: Message, state: FSMContext):
    name = message.text.strip()
    if not name:
        return await message.answer("Имя не может быть пустым:")
    data = await state.get_data()
    master_id = data['editing_master_id']
    await db.execute("UPDATE masters SET name = $1 WHERE id = $2", name, master_id)
    await state.clear()
    await message.answer(f"✅ Имя изменено на <b>{name}</b>.", parse_mode="HTML",
                         reply_markup=_master_menu(master_id))


# ──────────────────────────────────────────────
# Смена отдела
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_master_dept_") &
                       ~F.data.startswith("adm_master_dept_new_"))
async def master_change_dept_start(callback: CallbackQuery):
    if not await UserService.is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    master_id = int(callback.data.split("_")[-1])
    keyboard = await _dept_keyboard(f"adm_master_set_dept_{master_id}_")
    await callback.message.edit_text("Выберите новый отдел:", reply_markup=keyboard)


@router.callback_query(F.data.startswith("adm_master_set_dept_"))
async def master_set_dept(callback: CallbackQuery):
    parts = callback.data.split("_")          # adm master set dept {master_id} {dept_id}
    master_id, dept_id = int(parts[-2]), int(parts[-1])
    await db.execute("UPDATE masters SET department_id = $1 WHERE id = $2", dept_id, master_id)
    dept = await db.fetchrow("SELECT name FROM departments WHERE id = $1", dept_id)
    await callback.answer(f"Отдел изменён на «{dept['name']}»")
    # обновляем карточку
    row = await db.fetchrow("""
        SELECT m.*, d.name AS dept_name FROM masters m
        LEFT JOIN departments d ON m.department_id = d.id WHERE m.id = $1
    """, master_id)
    status = "✅ Активен" if row['is_active'] else "❌ Неактивен"
    text = (f"👤 <b>{row['name']}</b>\n"
            f"Отдел: {row['dept_name'] or '—'}\n"
            f"Статус: {status}")
    await callback.message.edit_text(text, reply_markup=_master_menu(master_id), parse_mode="HTML")


# ──────────────────────────────────────────────
# Вкл / Выкл мастера
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_master_toggle_"))
async def master_toggle(callback: CallbackQuery):
    if not await UserService.is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    master_id = int(callback.data.split("_")[-1])
    current = await db.fetchval("SELECT is_active FROM masters WHERE id = $1", master_id)
    await db.execute("UPDATE masters SET is_active = $1 WHERE id = $2", not current, master_id)
    await callback.answer("Статус изменён")
    # обновляем карточку
    row = await db.fetchrow("""
        SELECT m.*, d.name AS dept_name FROM masters m
        LEFT JOIN departments d ON m.department_id = d.id WHERE m.id = $1
    """, master_id)
    status = "✅ Активен" if row['is_active'] else "❌ Неактивен"
    text = (f"👤 <b>{row['name']}</b>\n"
            f"Отдел: {row['dept_name'] or '—'}\n"
            f"Статус: {status}")
    await callback.message.edit_text(text, reply_markup=_master_menu(master_id), parse_mode="HTML")


# ──────────────────────────────────────────────
# Удаление мастера
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_master_delete_"))
async def master_delete(callback: CallbackQuery):
    if not await UserService.is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    master_id = int(callback.data.split("_")[-1])
    name = await db.fetchval("SELECT name FROM masters WHERE id = $1", master_id)
    # мягкое удаление — деактивируем, чтобы не ломать старые записи
    await db.execute("UPDATE masters SET is_active = FALSE WHERE id = $1", master_id)
    keyboard = await _masters_list_keyboard()
    await callback.message.edit_text(f"🗑 Мастер <b>{name}</b> деактивирован.",
                                     reply_markup=keyboard, parse_mode="HTML")


# ──────────────────────────────────────────────
# Расписание мастера — календарь
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_master_sched_"))
async def master_schedule_calendar(callback: CallbackQuery):
    if not await UserService.is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    master_id = int(callback.data.split("_")[-1])
    name = await db.fetchval("SELECT name FROM masters WHERE id = $1", master_id)
    now = get_current_datetime_in_master_tz()
    keyboard = _schedule_calendar(master_id, now.year, now.month)
    await callback.message.edit_text(
        f"📅 Расписание мастера <b>{name}</b>\n\n"
        f"Выберите дату для настройки.\n"
        f"По умолчанию все дни рабочие: 10:00–21:00",
        reply_markup=keyboard, parse_mode="HTML"
    )


@router.callback_query(F.data.startswith("adm_sched_prev_") |
                       F.data.startswith("adm_sched_next_"))
async def schedule_cal_nav(callback: CallbackQuery):
    parts = callback.data.split("_")
    # adm sched prev/next {master_id} {year} {month}
    master_id, year, month = int(parts[3]), int(parts[4]), int(parts[5])
    if "prev" in callback.data:
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    else:
        month += 1
        if month == 13:
            month, year = 1, year + 1
    await callback.message.edit_reply_markup(
        reply_markup=_schedule_calendar(master_id, year, month)
    )


# ──────────────────────────────────────────────
# Расписание — конкретная дата
# ──────────────────────────────────────────────

async def _day_keyboard(master_id: int, day: date) -> InlineKeyboardMarkup:
    sched = await ScheduleService.get_master_schedule(master_id, day)
    date_str = day.isoformat()
    is_default = sched.id == 0  # дефолтное расписание (нет записи в БД)

    if sched.is_day_off:
        status_line = "❌ Выходной"
    else:
        status_line = f"🕐 {sched.start_time.strftime('%H:%M')}–{sched.end_time.strftime('%H:%M')}"
        if is_default:
            status_line += "  (по умолчанию)"

    buttons = [
        [InlineKeyboardButton(text=f"📋 Сейчас: {status_line}", callback_data="ignore")],
        [InlineKeyboardButton(text="⏰ Задать часы работы",
                              callback_data=f"adm_sched_sethours_{master_id}_{date_str}")],
        [InlineKeyboardButton(text="❌ Поставить выходной",
                              callback_data=f"adm_sched_off_{master_id}_{date_str}")],
    ]
    if not is_default:
        buttons.append([InlineKeyboardButton(
            text="🔄 Сбросить к умолчанию (10:00–21:00)",
            callback_data=f"adm_sched_reset_{master_id}_{date_str}"
        )])
    buttons.append([InlineKeyboardButton(
        text="🔙 Назад к календарю",
        callback_data=f"adm_master_sched_{master_id}"
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@router.callback_query(F.data.startswith("adm_sched_date_"))
async def schedule_day_menu(callback: CallbackQuery):
    if not await UserService.is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    parts = callback.data.split("_", 4)   # adm sched date {master_id} {date}
    master_id, date_str = int(parts[3]), parts[4]
    day = date.fromisoformat(date_str)
    name = await db.fetchval("SELECT name FROM masters WHERE id = $1", master_id)

    # Записи на этот день
    appts = await db.fetch("""
        SELECT a.appointment_date, a.total_duration, u.full_name
        FROM appointments a
        JOIN users u ON a.client_id = u.id
        WHERE a.master_id = $1
          AND DATE(a.appointment_date) = $2
          AND a.status IN ('pending','confirmed')
        ORDER BY a.appointment_date
    """, master_id, day)

    text = (f"👤 <b>{name}</b>  📅 {day.strftime('%d.%m.%Y')}\n\n")
    if appts:
        text += "<b>Записи на этот день:</b>\n"
        for a in appts:
            t = a['appointment_date'].strftime('%H:%M')
            end = (a['appointment_date'] + timedelta(minutes=a['total_duration'] or 60)).strftime('%H:%M')
            text += f"  • {t}–{end}  {a['full_name'] or '—'}\n"
        text += "\n"

    keyboard = await _day_keyboard(master_id, day)
    await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


# ──────────────────────────────────────────────
# Поставить выходной
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_sched_off_"))
async def schedule_set_off(callback: CallbackQuery):
    if not await UserService.is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    _, _, _, master_id_str, date_str = callback.data.split("_", 4)
    master_id, day = int(master_id_str), date.fromisoformat(date_str)
    await db.execute("""
        INSERT INTO master_schedule (master_id, date, is_day_off, start_time, end_time)
        VALUES ($1, $2, TRUE, NULL, NULL)
        ON CONFLICT (master_id, date) DO UPDATE
          SET is_day_off=TRUE, start_time=NULL, end_time=NULL
    """, master_id, day)
    await callback.answer("Выходной установлен")
    keyboard = await _day_keyboard(master_id, day)
    await callback.message.edit_reply_markup(reply_markup=keyboard)


# ──────────────────────────────────────────────
# Сбросить к умолчанию
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_sched_reset_"))
async def schedule_reset(callback: CallbackQuery):
    if not await UserService.is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    _, _, _, master_id_str, date_str = callback.data.split("_", 4)
    master_id, day = int(master_id_str), date.fromisoformat(date_str)
    await db.execute(
        "DELETE FROM master_schedule WHERE master_id = $1 AND date = $2",
        master_id, day
    )
    await callback.answer("Сброшено к умолчанию (10:00–21:00)")
    keyboard = await _day_keyboard(master_id, day)
    await callback.message.edit_reply_markup(reply_markup=keyboard)


# ──────────────────────────────────────────────
# Задать часы работы
# ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("adm_sched_sethours_"))
async def schedule_set_hours_start(callback: CallbackQuery, state: FSMContext):
    if not await UserService.is_admin(callback.from_user.id):
        return await callback.answer("Нет доступа", show_alert=True)
    _, _, _, master_id_str, date_str = callback.data.split("_", 4)
    master_id, day = int(master_id_str), date.fromisoformat(date_str)
    await state.update_data(hours_master_id=master_id, hours_date=date_str)
    await callback.message.edit_text(
        f"Введите рабочие часы для <b>{day.strftime('%d.%m.%Y')}</b>\n\n"
        f"Формат: <code>9:00-18:00</code> или <code>10-21</code>",
        parse_mode="HTML",
    )
    await state.set_state(MasterAdminStates.entering_hours)


@router.message(StateFilter(MasterAdminStates.entering_hours))
async def schedule_save_hours(message: Message, state: FSMContext):
    parsed = _parse_hours(message.text or "")
    if not parsed:
        return await message.answer(
            "Неверный формат. Введите как <code>9:00-18:00</code> или <code>10-21</code>:",
            parse_mode="HTML"
        )
    start_t, end_t = parsed
    data = await state.get_data()
    master_id = data['hours_master_id']
    day = date.fromisoformat(data['hours_date'])

    await db.execute("""
        INSERT INTO master_schedule (master_id, date, start_time, end_time, is_day_off)
        VALUES ($1, $2, $3, $4, FALSE)
        ON CONFLICT (master_id, date) DO UPDATE
          SET start_time=$3, end_time=$4, is_day_off=FALSE
    """, master_id, day, start_t, end_t)
    await state.clear()

    keyboard = await _day_keyboard(master_id, day)
    await message.answer(
        f"✅ {day.strftime('%d.%m.%Y')}: {start_t.strftime('%H:%M')}–{end_t.strftime('%H:%M')}",
        reply_markup=keyboard
    )
