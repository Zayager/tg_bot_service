"""Миграции базы данных"""
import logging
from database import db

logger = logging.getLogger(__name__)

async def create_tables():
    """Создание всех таблиц базы данных"""
    
    # Таблица пользователей
    await db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE NOT NULL,
            username VARCHAR(255),
            full_name VARCHAR(255),
            is_admin BOOLEAN DEFAULT FALSE,
            is_master BOOLEAN DEFAULT FALSE,
            timezone VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица услуг
    await db.execute("""
        CREATE TABLE IF NOT EXISTS services (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            price DECIMAL(10, 2) NOT NULL,
            duration_minutes INTEGER NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            is_additional BOOLEAN DEFAULT FALSE,
            order_index INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Добавляем поле is_additional если его нет
    try:
        await db.execute("""
            ALTER TABLE services ADD COLUMN IF NOT EXISTS is_additional BOOLEAN DEFAULT FALSE
        """)
    except:
        pass
    
    # Таблица расписания
    await db.execute("""
        CREATE TABLE IF NOT EXISTS schedule (
            id SERIAL PRIMARY KEY,
            date DATE NOT NULL,
            start_time TIME,
            end_time TIME,
            is_day_off BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date)
        )
    """)
    
    # Таблица записей
    await db.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id SERIAL PRIMARY KEY,
            client_id INTEGER NOT NULL REFERENCES users(id),
            service_id INTEGER NOT NULL REFERENCES services(id),
            appointment_date TIMESTAMP NOT NULL,
            status VARCHAR(50) DEFAULT 'pending',
            total_price DECIMAL(10, 2) DEFAULT 0,
            total_duration INTEGER DEFAULT 0,
            admin_comment TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Добавляем колонку admin_comment если она еще не существует (для существующих БД)
    try:
        await db.execute("""
            ALTER TABLE appointments
            ADD COLUMN IF NOT EXISTS admin_comment TEXT
        """)
    except Exception as e:
        pass

    # Пожелание клиента по мастеру
    try:
        await db.execute("""
            ALTER TABLE appointments
            ADD COLUMN IF NOT EXISTS client_note TEXT
        """)
    except Exception as e:
        pass

    # ──────────── Отделы ────────────
    await db.execute("""
        CREATE TABLE IF NOT EXISTS departments (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            order_index INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ──────────── Мастера ────────────
    await db.execute("""
        CREATE TABLE IF NOT EXISTS masters (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            department_id INTEGER REFERENCES departments(id),
            is_active BOOLEAN DEFAULT TRUE,
            order_index INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # ──────────── Расписание мастера ────────────
    await db.execute("""
        CREATE TABLE IF NOT EXISTS master_schedule (
            id SERIAL PRIMARY KEY,
            master_id INTEGER NOT NULL REFERENCES masters(id) ON DELETE CASCADE,
            date DATE NOT NULL,
            start_time TIME,
            end_time TIME,
            is_day_off BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(master_id, date)
        )
    """)

    # department_id в услугах
    try:
        await db.execute("""
            ALTER TABLE services
            ADD COLUMN IF NOT EXISTS department_id INTEGER REFERENCES departments(id)
        """)
    except Exception:
        pass

    # category (подкатегория внутри отдела, например "Стрижки", "Маникюр")
    try:
        await db.execute("""
            ALTER TABLE services
            ADD COLUMN IF NOT EXISTS category VARCHAR(100)
        """)
    except Exception:
        pass

    # master_id в записях
    try:
        await db.execute("""
            ALTER TABLE appointments
            ADD COLUMN IF NOT EXISTS master_id INTEGER REFERENCES masters(id)
        """)
    except Exception:
        pass

    # ──────────── Белый список мастеров для услуги ────────────
    # Если у услуги нет строк в этой таблице — услугу может оказывать любой мастер отдела.
    # Если строки есть — только перечисленные мастера.
    await db.execute("""
        CREATE TABLE IF NOT EXISTS master_services (
            master_id INTEGER NOT NULL REFERENCES masters(id) ON DELETE CASCADE,
            service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
            PRIMARY KEY (master_id, service_id)
        )
    """)

    # Сначала удаляем дубли и добавляем UNIQUE-ограничения,
    # чтобы последующие ON CONFLICT (column) DO NOTHING работали корректно
    await _cleanup_duplicates()

    # Отделы по умолчанию
    default_departments = [
        ('Парикмахерская', 1),
        ('Маникюр и педикюр', 2),
        ('Косметология', 3),
    ]
    for dept_name, order in default_departments:
        await db.execute("""
            INSERT INTO departments (name, order_index)
            VALUES ($1, $2)
            ON CONFLICT (name) DO NOTHING
        """, dept_name, order)
    
    # Таблица клиентов (расширенная информация)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE NOT NULL REFERENCES users(id),
            phone VARCHAR(20),
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица тегов клиентов
    await db.execute("""
        CREATE TABLE IF NOT EXISTS client_tags (
            id SERIAL PRIMARY KEY,
            client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            tag VARCHAR(100) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица заметок о клиентах
    await db.execute("""
        CREATE TABLE IF NOT EXISTS client_notes (
            id SERIAL PRIMARY KEY,
            client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            note TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица черного списка
    await db.execute("""
        CREATE TABLE IF NOT EXISTS blacklist (
            id SERIAL PRIMARY KEY,
            user_id INTEGER UNIQUE NOT NULL REFERENCES users(id),
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица истории записей
    await db.execute("""
        CREATE TABLE IF NOT EXISTS appointments_history (
            id SERIAL PRIMARY KEY,
            appointment_id INTEGER NOT NULL REFERENCES appointments(id),
            old_status VARCHAR(50),
            new_status VARCHAR(50),
            changed_by INTEGER REFERENCES users(id),
            change_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица настроек бота (кастомизация)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            id SERIAL PRIMARY KEY,
            key VARCHAR(255) UNIQUE NOT NULL,
            value TEXT NOT NULL,
            type VARCHAR(50) DEFAULT 'text',
            is_hidden BOOLEAN DEFAULT FALSE,
            order_index INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица настроек подтверждения записей
    await db.execute("""
        CREATE TABLE IF NOT EXISTS appointment_settings (
            id SERIAL PRIMARY KEY,
            require_confirmation BOOLEAN DEFAULT FALSE,
            reminder_24h_enabled BOOLEAN DEFAULT TRUE,
            reminder_1_2h_enabled BOOLEAN DEFAULT TRUE,
            reminder_interval_hours INTEGER DEFAULT 2,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица информации (адрес, контакты, соцсети и т.д.)
    await db.execute("""
        CREATE TABLE IF NOT EXISTS info_sections (
            id SERIAL PRIMARY KEY,
            key VARCHAR(100) UNIQUE NOT NULL,
            title VARCHAR(255) NOT NULL,
            content TEXT,
            is_active BOOLEAN DEFAULT TRUE,
            order_index INTEGER DEFAULT 0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица FAQ
    await db.execute("""
        CREATE TABLE IF NOT EXISTS faq (
            id SERIAL PRIMARY KEY,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            order_index INTEGER DEFAULT 0,
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица напоминаний
    await db.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id SERIAL PRIMARY KEY,
            appointment_id INTEGER NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
            reminder_type VARCHAR(50) NOT NULL,  -- 24h, 1-2h, follow_up
            scheduled_at TIMESTAMP NOT NULL,
            sent BOOLEAN DEFAULT FALSE,
            sent_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Создаем индекс для быстрого поиска по дате расписания
    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_schedule_date ON schedule(date)
    """)
    
    # Создаем индекс для поиска записей по дате
    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_appointments_date ON appointments(appointment_date)
    """)
    
    # Создаем индекс для поиска записей клиента
    await db.execute("""
        CREATE INDEX IF NOT EXISTS idx_appointments_client ON appointments(client_id)
    """)
    
    # Вставляем начальные настройки подтверждения
    await db.execute("""
        INSERT INTO appointment_settings (id, require_confirmation, reminder_24h_enabled, reminder_1_2h_enabled, reminder_interval_hours)
        VALUES (1, TRUE, TRUE, TRUE, 2)
        ON CONFLICT DO NOTHING
    """)
    
    # Таблица дополнительных услуг для записей
    await db.execute("""
        CREATE TABLE IF NOT EXISTS appointment_additional_services (
            id SERIAL PRIMARY KEY,
            appointment_id INTEGER NOT NULL REFERENCES appointments(id) ON DELETE CASCADE,
            service_id INTEGER NOT NULL REFERENCES services(id),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица связей основных и дополнительных услуг
    # Если main_service_id IS NULL, то дополнительная услуга доступна для всех основных услуг
    await db.execute("""
        CREATE TABLE IF NOT EXISTS services_additional_links (
            id SERIAL PRIMARY KEY,
            additional_service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
            main_service_id INTEGER REFERENCES services(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(additional_service_id, main_service_id)
        )
    """)
    
    # Вставляем начальные разделы информации
    initial_info_sections = [
        ('address', 'Адрес', '', 1),
        ('map', 'Карта', '', 2),
        ('how_to_get', 'Как добраться', '', 3),
        ('contacts', 'Контакты', '', 4),
        ('social_media', 'Соцсети', '', 5),
        ('portfolio', 'Портфолио', '', 6),
        ('master_description', 'Описание мастера', '', 7),
        ('booking_rules', 'Правила записи', '', 8),
    ]
    
    for key, title, content, order_idx in initial_info_sections:
        await db.execute("""
            INSERT INTO info_sections (key, title, content, order_index)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (key) DO NOTHING
        """, key, title, content, order_idx)
    
    # Заполняем услуги из прайс-листа
    await _seed_services()

    logger.info("Таблицы базы данных созданы")


# ──────────────────────────────────────────────
# Данные прайс-листа
# (category, name, price, duration_minutes, dept_id, description)
# dept_id: 1=Парикмахерская, 2=Маникюр и педикюр, 3=Косметология
# ──────────────────────────────────────────────
_SERVICES_SEED = [
    # ── Парикмахерская: Стрижки ──
    ("Стрижки", "Стрижка мужская", 2000.0, 30, 1, None),
    ("Стрижки", "Стрижка женская с укладкой (короткие/средние/длинные/оч.длинные)", 2000.0, 60, 1, "2000–2800 ₽"),
    ("Стрижки", "Стрижка горячими ножницами (короткие/средние/длинные)", 2500.0, 90, 1, "2500–3300 ₽"),
    ("Стрижки", "Детская стрижка (до 7 лет)", 1500.0, 30, 1, None),
    ("Стрижки", "Стрижка сечёных волос (гор. ножницами)", 1300.0, 45, 1, "1300–1700 ₽"),
    ("Стрижки", "Стрижка чёлки", 700.0, 15, 1, None),
    # ── Парикмахерская: Укладки ──
    ("Укладки", "Укладка (короткие/средние/длинные/оч.длинные)", 1500.0, 30, 1, "1500–2500 ₽"),
    ("Укладки", "Укладка утюгами", 1200.0, 30, 1, None),
    ("Укладки", "Укладка вечерняя", 3500.0, 60, 1, None),
    ("Укладки", "Укладка наращенных волос", 3000.0, 45, 1, None),
    ("Укладки", "Прическа праздничная", 5500.0, 90, 1, None),
    ("Укладки", "Доп. укладочное средство", 200.0, 5, 1, None),
    ("Укладки", "Массаж головы", 400.0, 15, 1, None),
    ("Укладки", "Мытьё головы + сушка", 700.0, 30, 1, "700–1300 ₽"),
    ("Укладки", "Маски для волос (средние/длинные/оч.длинные)", 600.0, 20, 1, "600–1000 ₽"),
    # ── Парикмахерская: Окрашивание ──
    ("Окрашивание", "Окрашивание INSIGHT тон в тон (с уходом)", 4100.0, 90, 1, None),
    ("Окрашивание", "Окрашивание INSIGHT (до 2 см) (с уходом)", 3800.0, 90, 1, None),
    ("Окрашивание", "Окрашивание с уходом (WELLA, Loreal, FANE)", 4800.0, 120, 1, None),
    ("Окрашивание", "Окрашивание корней (WELLA, Loreal, FANE) (с уходом)", 4300.0, 90, 1, None),
    ("Окрашивание", "Тонирование", 4000.0, 60, 1, None),
    ("Окрашивание", "Окрашивание (краска клиента)", 3000.0, 90, 1, None),
    ("Окрашивание", "Укладка после окрашивания (без укладочных средств)", 600.0, 30, 1, "600–1200 ₽"),
    ("Окрашивание", "Камуфляж", 1600.0, 30, 1, None),
    ("Окрашивание", "Окрашивание одной пряди", 600.0, 30, 1, None),
    ("Окрашивание", "Удаление нежелательного оттенка", 2500.0, 120, 1, None),
    ("Окрашивание", "Колорирование (от 2-х и более цветов)", 6800.0, 180, 1, None),
    ("Окрашивание", "Креативное окрашивание", 9000.0, 240, 1, None),
    ("Окрашивание", "Мелирование (Blondor - пудра)", 4100.0, 120, 1, None),
    ("Окрашивание", "Мелирование + тонирование", 7800.0, 150, 1, None),
    ("Окрашивание", "Мелирование + окрашивание", 8500.0, 150, 1, None),
    ("Окрашивание", "Мелирование (неполное или частичное)", 2500.0, 90, 1, "2500–3600 ₽"),
    ("Окрашивание", "Осветление волос (Blondor - пудра)", 3800.0, 90, 1, None),
    ("Окрашивание", "Осветление 1-ой пряди", 600.0, 30, 1, None),
    ("Окрашивание", "Химическая завивка", 4500.0, 120, 1, None),
    # ── Парикмахерская: Уходы ──
    ("Уходы", "Программа #Абсолютное счастье для волос (короткие/средние/длинные/оч.длинные)", 3400.0, 60, 1, "3400–6800 ₽"),
    ("Уходы", "Программа #Блеск и сила", 2200.0, 60, 1, "2200–3900 ₽"),
    ("Уходы", "Программа #Счастье для волос (короткие/средние/длинные/оч.длинные)", 2200.0, 60, 1, "2200–3900 ₽"),
    ("Уходы", "Сыворотка по типу волос (LEBEL)", 600.0, 10, 1, None),
    ("Уходы", "Пилинг кожи головы", 400.0, 15, 1, None),
    ("Уходы", "Армирование волос (INSIGHT REBUILD)", 2000.0, 60, 1, "2000–3700 ₽"),
    ("Уходы", "Маски для волос", 600.0, 20, 1, "600–1000 ₽"),
    ("Уходы", "Массаж головы", 400.0, 15, 1, None),
    # ── Маникюр и педикюр: Маникюр ──
    ("Маникюр", "Маникюр (аппаратный, комбинированный, классический, европейский)", 1300.0, 60, 2, None),
    ("Маникюр", "Маникюр мужской", 1500.0, 60, 2, None),
    ("Маникюр", "Маникюр детский (до 10 лет)", 1000.0, 30, 2, None),
    ("Маникюр", "Маникюр + покрытие гель-лак/френч (снятие+выравнивание)", 2800.0, 90, 2, "2800–3000 ₽"),
    ("Маникюр", "Маникюр + покрытие гель-лак/френч (без снятия)", 2500.0, 75, 2, "2500–2700 ₽"),
    ("Маникюр", "Покрытие лак", 500.0, 20, 2, None),
    ("Маникюр", "Покрытие лечебной основой", 200.0, 10, 2, None),
    ("Маникюр", "Снятие лака", 200.0, 10, 2, None),
    ("Маникюр", "Покрытие гель-лак", 1500.0, 30, 2, None),
    ('Маникюр', 'Покрытие "Френч" гель-лак', 1700.0, 30, 2, None),
    ("Маникюр", "Снятие гель-лак (покрытие салона/ чужое)", 500.0, 20, 2, "500–800 ₽"),
    ("Маникюр", "Реставрация одного ногтя гель-лак", 300.0, 15, 2, None),
    ("Маникюр", "Парафинотерапия для рук (теплый)", 400.0, 15, 2, None),
    ("Маникюр", "Холодный парафин для рук", 300.0, 10, 2, None),
    ("Маникюр", "Пилинг, скраб для рук", 300.0, 10, 2, None),
    ("Маникюр", "Крем, лосьон для рук", 100.0, 5, 2, None),
    # ── Маникюр и педикюр: Педикюр ──
    ("Педикюр", "Аппаратный, комбинированный педикюр (1 уровень/2 уровень сложности)", 2200.0, 90, 2, "2200–2400 ₽"),
    ("Педикюр", "Мужской педикюр/ сложный", 2500.0, 90, 2, "2500–2700 ₽"),
    ("Педикюр", "Аппаратный, комбинированный педикюр + покрытие гель-лак (без снятия)", 3200.0, 120, 2, "3200–3400 ₽"),
    ("Педикюр", "Аппаратный, комбинированный педикюр + покрытие гель-лак (снятие старого покрытия)", 3600.0, 130, 2, "3600–3800 ₽"),
    ("Педикюр", "Обработка стопы", 1500.0, 30, 2, None),
    ("Педикюр", "Обработка пальцев ног", 1500.0, 30, 2, None),
    ("Педикюр", "Пилинг, скраб для ног", 400.0, 10, 2, None),
    ("Педикюр", "Парафинотерапия для ног (теплый)", 450.0, 15, 2, None),
    ("Педикюр", "Обработка мозоли", 100.0, 10, 2, None),
    ("Педикюр", "Обработка стержневой мозоли", 300.0, 15, 2, None),
    ("Педикюр", "Обработка трещин", 400.0, 15, 2, None),
    ("Педикюр", "Лечебные мази", 200.0, 5, 2, None),
    ("Педикюр", "Обработка вросшего ногтя (без воспаления)", 200.0, 15, 2, None),
    ("Педикюр", "Обработка вросшего ногтя 1 сторона (тампонада и резекция)", 300.0, 20, 2, None),
    # ── Маникюр и педикюр: Наращивание и дизайн ──
    ("Наращивание и дизайн", "Разгрузка для ногтевой пластины", 300.0, 15, 2, None),
    ("Наращивание и дизайн", "Установка пластины ONYCLIP", 3500.0, 30, 2, None),
    ("Наращивание и дизайн", "Наращивание", 4500.0, 120, 2, None),
    ("Наращивание и дизайн", "Наращивание (короткие ногти)", 4000.0, 90, 2, None),
    ('Наращивание и дизайн', 'Наращивание "Френч"', 5000.0, 150, 2, None),
    ('Наращивание и дизайн', 'Наращивание "Френч" (короткие ногти)', 4500.0, 120, 2, None),
    ("Наращивание и дизайн", "Снятие наращенных ногтей", 1000.0, 45, 2, None),
    ("Наращивание и дизайн", "Снятие с последующим наращиванием", 500.0, 15, 2, None),
    ("Наращивание и дизайн", "Наращивание одного ногтя (покрытие салона/чужое)", 450.0, 20, 2, "450–600 ₽"),
    ("Наращивание и дизайн", "Снятие одного наращенного ногтя", 300.0, 10, 2, None),
    ("Наращивание и дизайн", "Реставрация ногтя (гель, акрил)", 450.0, 15, 2, None),
    ("Наращивание и дизайн", "Дизайн одного ногтя (аэрография, стемпинг и др.)", 100.0, 10, 2, None),
    ("Наращивание и дизайн", "Страз, бисер, фольга, втирка, камифубуки (за шт.)", 50.0, 5, 2, None),
    # ── Косметология: Пилинги ──
    ("Пилинги (Skin Synergy)", "Очищение", 200.0, 10, 3, None),
    ("Пилинги (Skin Synergy)", "Очищение + демакияж", 500.0, 15, 3, None),
    ("Пилинги (Skin Synergy)", "Мультикислотные пилинги", 3000.0, 60, 3, None),
    ("Пилинги (Skin Synergy)", "Пилинг комбинированный (Молочный, миндальный и др.)", 4000.0, 60, 3, "4000–5000 ₽"),
    ("Пилинги (Skin Synergy)", "Пилинг DCA (мгновенный эффект)", 5000.0, 45, 3, None),
    ("Пилинги (Skin Synergy)", "Ретиноевый CIMEL (желтый)", 8000.0, 60, 3, None),
    ("Пилинги (Skin Synergy)", "Ретиноловый Skin Synergy (желтый)", 6000.0, 60, 3, None),
    ('Пилинги (Skin Synergy)', '"Аква" пилинг', 1500.0, 30, 3, None),
    ("Пилинги (Skin Synergy)", "Ультразвуковой пилинг", 1500.0, 30, 3, None),
    # ── Косметология: Чистка лица ──
    ("Чистка лица (Meillume)", "Деликатная чистка для чувствительной и сухой кожи", 5000.0, 90, 3, None),
    ("Чистка лица (Meillume)", "Атравматичная чистка жирной и комбинированной кожи", 4500.0, 90, 3, None),
    ("Чистка лица (Meillume)", "Экспресс чистка с ультразвуком, механическая", 3500.0, 60, 3, None),
    # ── Косметология: Массажи ──
    ("Массажи", "Дарсонвализация волосистой части головы", 600.0, 20, 3, None),
    ("Массажи", "Дарсонвализация лица", 600.0, 20, 3, None),
    ("Массажи", "Деструкция милиумов 1эл.", 200.0, 15, 3, None),
    ("Массажи", "Лимфодренажный массаж лица", 2000.0, 45, 3, None),
    ("Массажи", "Миофасциальный массаж лица/ демакияж+крем", 3000.0, 60, 3, "3000–4000 ₽"),
    ("Массажи", "Массаж шейно-воротниковой зоны", 1000.0, 30, 3, None),
    ("Массажи", "Массаж + пилинг", 5000.0, 75, 3, None),
    ("Массажи", "Скульптурный массаж лица", 2500.0, 60, 3, None),
    # ── Косметология: Маски и сыворотки ──
    ("Маски и сыворотки", "Маски по проблеме", 1500.0, 20, 3, None),
    ("Маски и сыворотки", "Альгинатная + сыворотка", 2000.0, 30, 3, None),
    ("Маски и сыворотки", "Альгинатная + маска", 2000.0, 30, 3, None),
    ("Маски и сыворотки", "Маска для области вокруг глаз", 1000.0, 20, 3, None),
    ("Маски и сыворотки", "Завершающий крем", 500.0, 5, 3, None),
    ("Маски и сыворотки", "Сыворотка", 700.0, 10, 3, None),
    # ── Косметология: Аппаратные процедуры ──
    ("Аппаратные процедуры", "Микротоковая терапия", 3000.0, 60, 3, None),
    ("Аппаратные процедуры", "Уход для жирной кожи/ розацеа,купероз", 5000.0, 75, 3, "5000–6000 ₽"),
    ("Аппаратные процедуры", "Увлажняющий, Осветляющий уход", 6000.0, 75, 3, None),
    ("Аппаратные процедуры", "Омолаживающий уход для периорбитальной области", 2000.0, 45, 3, None),
    ("Аппаратные процедуры", "Лифтинг anti-age", 7000.0, 90, 3, None),
    ("Аппаратные процедуры", "Омолаживающий уход для периорбитальной области (расширенный)", 2500.0, 45, 3, None),
    ('Аппаратные процедуры', 'Экспресс процедура "на выход" барофорез (Renocode) (Лицо + шея)', 3000.0, 45, 3, "3000–4000 ₽"),
    ("Аппаратные процедуры", "Аква пилинг + вибрационный массаж", 1500.0, 30, 3, None),
    ("Аппаратные процедуры", "Аква пилинг + энзимная маска", 2000.0, 30, 3, None),
    ("Аппаратные процедуры", "Карбокситерапия лицо", 4000.0, 45, 3, None),
    # ── Косметология: Брови и ресницы ──
    ("Брови и ресницы", "Окрашивание бровей Refecto Cil", 700.0, 20, 3, None),
    ("Брови и ресницы", "Окрашивание ресниц", 900.0, 20, 3, None),
    ("Брови и ресницы", "БИО Окрашивание бровей (хна)", 1000.0, 30, 3, None),
    ("Брови и ресницы", "Коррекция бровей (простая/сложная форма)", 600.0, 20, 3, "600–700 ₽"),
    ("Брови и ресницы", "Комплекс 3 (окрашивание бровей, ресниц + коррекция)", 2000.0, 45, 3, None),
    ("Брови и ресницы", "Комплекс 2 (окрашивание ресниц + коррекция бровей)", 1400.0, 35, 3, None),
    ("Брови и ресницы", "Комплекс 1 (окрашивание бровей + коррекция) (простая/сложная форма)", 1200.0, 30, 3, "1200–1300 ₽"),
    ("Брови и ресницы", "Ламинирование ресниц", 3000.0, 60, 3, None),
    ("Брови и ресницы", "Ламинирование ресниц + окрашивание", 3000.0, 70, 3, None),
    ("Брови и ресницы", "Ламинирование бровей + окрашивание", 3500.0, 60, 3, None),
    # ── Косметология: Наращивание ресниц ──
    ("Наращивание ресниц", "Классическое", 4000.0, 120, 3, None),
    ("Наращивание ресниц", "3D", 5000.0, 150, 3, None),
    ("Наращивание ресниц", "Неполное наращивание", 1000.0, 60, 3, "1000–3000 ₽"),
    ("Наращивание ресниц", "Коррекция ресниц", 1000.0, 60, 3, None),
    ("Наращивание ресниц", "Снятие ресниц", 800.0, 30, 3, None),
    # ── Косметология: Пирсинг ──
    ("Пирсинг", "Установка серёжек в уши аппаратом (одно ухо)", 800.0, 10, 3, None),
    ("Пирсинг", "Серьги в уши", 400.0, 5, 3, None),
    # ── Косметология: Биоэпиляция воском ──
    ("Биоэпиляция воском", "Голени до колена/с коленом", 1000.0, 30, 3, "1000–1200 ₽"),
    ("Биоэпиляция воском", "Бедра", 1200.0, 30, 3, None),
    ("Биоэпиляция воском", "Руки до локтя/с локтем", 900.0, 20, 3, "900–1000 ₽"),
    ("Биоэпиляция воском", "Руки полностью", 1500.0, 30, 3, None),
    ("Биоэпиляция воском", "Ноги полностью", 2200.0, 60, 3, None),
    ("Биоэпиляция воском", "Спины/ часть", 1500.0, 40, 3, "1500–3000 ₽"),
    ("Биоэпиляция воском", "Подмышек", 800.0, 15, 3, None),
    ("Биоэпиляция воском", "Лица ( одна/две зоны )", 400.0, 15, 3, "400–700 ₽"),
    ("Биоэпиляция воском", "Классическое бикини", 1600.0, 30, 3, None),
    ("Биоэпиляция воском", "Глубокое бикини (первый/второй уровень)", 2400.0, 45, 3, "2400–2800 ₽"),
    ("Биоэпиляция воском", "Ягодицы", 1000.0, 20, 3, None),
    # ── Косметология: Биоэпиляция сахарной пастой ──
    ("Биоэпиляция сахарной пастой", "Голени", 1500.0, 30, 3, None),
    ("Биоэпиляция сахарной пастой", "Руки до локтя", 1000.0, 20, 3, None),
    ("Биоэпиляция сахарной пастой", "Руки полностью", 1800.0, 30, 3, None),
    ("Биоэпиляция сахарной пастой", "Подмышек", 800.0, 15, 3, None),
    ("Биоэпиляция сахарной пастой", "Классическое бикини", 2000.0, 30, 3, None),
    ("Биоэпиляция сахарной пастой", "Глубокое бикини (первый уровень)", 2600.0, 45, 3, None),
    ("Биоэпиляция сахарной пастой", "Глубокое бикини (второй уровень)", 3000.0, 60, 3, None),
    # ── Косметология: Электроэпиляция ──
    ("Электроэпиляция", "за минуту", 45.0, 60, 3, None),
    # ── Косметология: Лазерная эпиляция ──
    ("Лазерная эпиляция", "Верхняя губа", 500.0, 15, 3, None),
    ("Лазерная эпиляция", "Подбородок", 500.0, 15, 3, None),
    ("Лазерная эпиляция", "Бакенбарды, щека", 800.0, 20, 3, None),
    ("Лазерная эпиляция", "Шея", 850.0, 20, 3, None),
    ("Лазерная эпиляция", "Межбровка", 400.0, 10, 3, None),
    ("Лазерная эпиляция", "Лицо полностью", 1600.0, 30, 3, None),
    ("Лазерная эпиляция", "Подмышки", 700.0, 15, 3, None),
    ("Лазерная эпиляция", "Ореолы", 650.0, 15, 3, None),
    ("Лазерная эпиляция", "Декольте", 1100.0, 20, 3, None),
    ("Лазерная эпиляция", "Голень", 1800.0, 30, 3, None),
    ("Лазерная эпиляция", "Бедро (часть)", 1000.0, 20, 3, None),
    ("Лазерная эпиляция", "Бедро", 2000.0, 30, 3, None),
    ("Лазерная эпиляция", "Ноги полностью", 3500.0, 60, 3, None),
    ("Лазерная эпиляция", "Спина", 3000.0, 45, 3, None),
    ("Лазерная эпиляция", "Спина + плечи", 3500.0, 60, 3, None),
    ("Лазерная эпиляция", "Кисти рук", 800.0, 15, 3, None),
    ("Лазерная эпиляция", "Руки до локтя", 1200.0, 20, 3, None),
    ("Лазерная эпиляция", "Живот дорожка", 400.0, 10, 3, None),
    ("Лазерная эпиляция", "Живот полностью", 1850.0, 30, 3, None),
    ("Лазерная эпиляция", "Ягодицы", 1750.0, 30, 3, None),
    ("Лазерная эпиляция", "Бикини классика", 1200.0, 20, 3, None),
    ("Лазерная эпиляция", "Бикини глубокое", 1700.0, 30, 3, None),
    # ── Косметология: Комплексы лазерной эпиляции ──
    ("Комплексы лазерной эпиляции", "Всё тело", 7000.0, 120, 3, None),
    ("Комплексы лазерной эпиляции", "Бикини + подмышки", 2200.0, 30, 3, None),
    ("Комплексы лазерной эпиляции", "Бикини + голень", 3200.0, 45, 3, None),
    ("Комплексы лазерной эпиляции", "Бикини + голень + подмышки", 3900.0, 60, 3, None),
    ("Комплексы лазерной эпиляции", "Бикини + ноги полностью", 5000.0, 75, 3, None),
    ("Комплексы лазерной эпиляции", "Бикини + ноги полностью + подмышки", 5700.0, 90, 3, None),
    ("Комплексы лазерной эпиляции", "Ноги полностью + руки полностью", 5200.0, 90, 3, None),
    ("Комплексы лазерной эпиляции", "Бикини + подмышки + бедра (часть)", 3200.0, 45, 3, None),
    ("Комплексы лазерной эпиляции", "Бикини + подмышки + руки (до локтя)", 3400.0, 45, 3, None),
    ("Комплексы лазерной эпиляции", "Ноги полностью + подмышки", 3950.0, 75, 3, None),
    ("Комплексы лазерной эпиляции", "Голень + подмышки", 2300.0, 40, 3, None),
    ("Комплексы лазерной эпиляции", "Руки (до локтя) + голень", 2900.0, 45, 3, None),
    # ── Косметология: LPG массаж ──
    ("LPG массаж", "Массаж 30 мин. (один сеанс)", 1300.0, 30, 3, None),
    ("LPG массаж", "Массаж 45 мин. (один сеанс)", 1500.0, 45, 3, None),
    ("LPG массаж", "Массаж 1ч (один сеанс)", 2000.0, 60, 3, None),
    ("LPG массаж", "Абонемент 30 м. 5 сеансов", 6000.0, 30, 3, None),
    ("LPG массаж", "Абонемент 30 м. 10 сеансов", 11000.0, 30, 3, None),
    ("LPG массаж", "Абонемент 30 м. 15 сеансов", 14500.0, 30, 3, None),
    ("LPG массаж", "Абонемент 45 м. 5 сеансов", 7000.0, 45, 3, None),
    ("LPG массаж", "Абонемент 45 м. 10 сеансов", 13000.0, 45, 3, None),
    ("LPG массаж", "Абонемент 45 м. 15 сеансов", 18000.0, 45, 3, None),
    ("LPG массаж", "Костюм", 1000.0, 5, 3, None),
    ("LPG массаж", "Аренда костюма", 200.0, 5, 3, None),
    # ── Косметология: Коррекция фигуры ──
    ("Коррекция фигуры", "Кавитация (1 сеанс/2 зоны)", 1300.0, 30, 3, "1300–2000 ₽"),
    ("Коррекция фигуры", "Кавитация (5 сеансов)", 5000.0, 30, 3, None),
    ("Коррекция фигуры", "Кавитация (10 сеансов)", 8500.0, 30, 3, None),
    ("Коррекция фигуры", "RF –лифтинг (1 сеанс/2 зоны)", 1300.0, 30, 3, "1300–2000 ₽"),
    ("Коррекция фигуры", "RF –лифтинг (5 сеансов)", 5000.0, 30, 3, None),
    ("Коррекция фигуры", "RF –лифтинг (10 сеансов)", 8500.0, 30, 3, None),
    ("Коррекция фигуры", "Горячий вакуумный массаж с RF (1 сеанс/2 зоны)", 1300.0, 30, 3, "1300–2000 ₽"),
    ("Коррекция фигуры", "Горячий вакуумный массаж с RF (5 сеансов)", 5000.0, 30, 3, None),
    ("Коррекция фигуры", "Горячий вакуумный массаж с RF (10 сеансов)", 8500.0, 30, 3, None),
    ("Коррекция фигуры", "Лазерный липолиз (1 сеанс)", 1300.0, 30, 3, None),
    ("Коррекция фигуры", "Лазерный липолиз (5 сеансов)", 5000.0, 30, 3, None),
    ("Коррекция фигуры", "Лазерный липолиз (10 сеансов)", 8500.0, 30, 3, None),
    ("Коррекция фигуры", "Лазерный липолиз (15 сеансов)", 13000.0, 30, 3, None),
]


async def _cleanup_duplicates():
    """Удаляет дублирующиеся строки из departments и services,
    затем добавляет UNIQUE-ограничения чтобы дублей больше не было."""

    # ── 1. Дубли отделов ──────────────────────────────────────────────────
    dept_groups = await db.fetch("""
        SELECT name, MIN(id) AS keep_id, array_agg(id ORDER BY id) AS all_ids
        FROM departments
        GROUP BY name
        HAVING COUNT(*) > 1
    """)
    for row in dept_groups:
        keep_id = row['keep_id']
        dup_ids = [i for i in row['all_ids'] if i != keep_id]
        # Переносим ссылки
        await db.execute(
            "UPDATE services SET department_id = $1 WHERE department_id = ANY($2::int[])",
            keep_id, dup_ids
        )
        await db.execute(
            "UPDATE masters SET department_id = $1 WHERE department_id = ANY($2::int[])",
            keep_id, dup_ids
        )
        await db.execute("DELETE FROM departments WHERE id = ANY($1::int[])", dup_ids)
        logger.info(f"Удалены дубли отдела '{row['name']}': {dup_ids}")

    # UNIQUE (name) на departments — безопасно, дублей уже нет
    try:
        await db.execute(
            "ALTER TABLE departments ADD CONSTRAINT departments_name_unique UNIQUE (name)"
        )
        logger.info("Добавлен UNIQUE(name) на таблицу departments")
    except Exception:
        pass  # ограничение уже существует

    # ── 2. Дубли услуг ────────────────────────────────────────────────────
    svc_groups = await db.fetch("""
        SELECT name, department_id, MIN(id) AS keep_id, array_agg(id ORDER BY id) AS all_ids
        FROM services
        GROUP BY name, department_id
        HAVING COUNT(*) > 1
    """)
    for row in svc_groups:
        keep_id = row['keep_id']
        dup_ids = [i for i in row['all_ids'] if i != keep_id]
        # Переносим ссылки в appointments
        await db.execute(
            "UPDATE appointments SET service_id = $1 WHERE service_id = ANY($2::int[])",
            keep_id, dup_ids
        )
        # Удаляем дублирующиеся дополнительные услуги в записях
        await db.execute(
            "DELETE FROM appointment_additional_services WHERE service_id = ANY($1::int[])",
            dup_ids
        )
        # Удаляем связи дополнительных услуг
        await db.execute(
            "DELETE FROM services_additional_links "
            "WHERE additional_service_id = ANY($1::int[]) OR main_service_id = ANY($1::int[])",
            dup_ids
        )
        # Удаляем белые списки мастеров для дублей
        await db.execute(
            "DELETE FROM master_services WHERE service_id = ANY($1::int[])",
            dup_ids
        )
        await db.execute("DELETE FROM services WHERE id = ANY($1::int[])", dup_ids)
        logger.info(f"Удалены дубли услуги '{row['name']}' (dept={row['department_id']}): {dup_ids}")

    # UNIQUE (name, department_id) на services
    try:
        await db.execute(
            "ALTER TABLE services "
            "ADD CONSTRAINT services_name_dept_unique UNIQUE (name, department_id)"
        )
        logger.info("Добавлен UNIQUE(name, department_id) на таблицу services")
    except Exception:
        pass  # ограничение уже существует


_DEPT_INDEX_NAMES = {
    1: 'Парикмахерская',
    2: 'Маникюр и педикюр',
    3: 'Косметология',
}

async def _seed_services():
    """Вставить услуги из прайс-листа. Пропускает уже существующие (по имени + dept_id).
    Получает реальные ID отделов по их именам — не зависит от хардкоженных значений."""
    # Загружаем реальные ID отделов из БД
    dept_map: dict = {}
    for idx, dept_name in _DEPT_INDEX_NAMES.items():
        row = await db.fetchrow("SELECT id FROM departments WHERE name = $1", dept_name)
        if row:
            dept_map[idx] = row['id']

    if not dept_map:
        logger.warning("Отделы не найдены — услуги не будут добавлены")
        return

    for i, (category, name, price, duration, dept_idx, description) in enumerate(_SERVICES_SEED):
        dept_id = dept_map.get(dept_idx)
        if dept_id is None:
            continue  # отдел не найден, пропускаем услугу
        await db.execute("""
            INSERT INTO services
                (name, description, price, duration_minutes, department_id, category, order_index, is_active, is_additional)
            VALUES ($1, $2, $3, $4, $5, $6, $7, TRUE, FALSE)
            ON CONFLICT (name, department_id) DO NOTHING
        """, name, description, price, duration, dept_id, category, i + 1)

