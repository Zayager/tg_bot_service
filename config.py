"""Конфигурация бота"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Загружаем переменные окружения
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

# Токен бота (обязательно)
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    print("❌ ОШИБКА: BOT_TOKEN не установлен в .env файле!")
    print("   Создайте файл .env на основе .env.example и заполните все необходимые значения.")
    sys.exit(1)

# ID администратора для системных сообщений (обязательно)
ADMIN_ID_STR = os.getenv('ADMIN_ID')
if not ADMIN_ID_STR:
    print("❌ ОШИБКА: ADMIN_ID не установлен в .env файле!")
    sys.exit(1)
try:
    ADMIN_ID = int(ADMIN_ID_STR)
except ValueError:
    print(f"❌ ОШИБКА: ADMIN_ID должен быть числом, получено: {ADMIN_ID_STR}")
    sys.exit(1)

LOG_ADMIN_ID_STR = os.getenv('LOG_ADMIN_ID', ADMIN_ID_STR)
try:
    LOG_ADMIN_ID = int(LOG_ADMIN_ID_STR)
except ValueError:
    print(f"❌ ОШИБКА: LOG_ADMIN_ID должен быть числом, получено: {LOG_ADMIN_ID_STR}")
    sys.exit(1)

# Настройки базы данных PostgreSQL (обязательно)
DB_HOST = os.getenv('DB_HOST')
DB_PORT_STR = os.getenv('DB_PORT')
DB_NAME = os.getenv('DB_NAME')
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')

if not all([DB_HOST, DB_PORT_STR, DB_NAME, DB_USER]) or DB_PASSWORD is None:
    print("❌ ОШИБКА: Не все настройки базы данных установлены в .env файле!")
    print("   Требуются: DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD")
    sys.exit(1)

try:
    DB_PORT = int(DB_PORT_STR)
except ValueError:
    print(f"❌ ОШИБКА: DB_PORT должен быть числом, получено: {DB_PORT_STR}")
    sys.exit(1)

# Часовой пояс мастера
MASTER_TIMEZONE = os.getenv('MASTER_TIMEZONE', 'Europe/Moscow')

# Формат строки подключения к БД (пароль может быть пустым, но нужно обработать это правильно)
if DB_PASSWORD:
    DATABASE_URL = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
else:
    DATABASE_URL = f"postgresql://{DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

