"""Скрипт для проверки настроек перед запуском"""
import sys
import os
from pathlib import Path

def check_env_file():
    """Проверка наличия .env файла"""
    env_path = Path(__file__).parent / '.env'
    if not env_path.exists():
        print("❌ Файл .env не найден!")
        print("   Создайте файл .env на основе следующего шаблона:")
        print("\n" + "="*50)
        print("BOT_TOKEN=your_bot_token_here")
        print("ADMIN_ID=your_admin_id_here")
        print("LOG_ADMIN_ID=your_admin_id_here")
        print("\n# PostgreSQL")
        print("DB_HOST=localhost")
        print("DB_PORT=5432")
        print("DB_NAME=beauty_bot")
        print("DB_USER=postgres")
        print("DB_PASSWORD=your_password_here")
        print("\n# Timezone")
        print("MASTER_TIMEZONE=Europe/Moscow")
        print("="*50 + "\n")
        return False
    
    # Загружаем переменные
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=env_path)
    
    bot_token = os.getenv('BOT_TOKEN', '')
    if not bot_token or bot_token == 'your_bot_token_here':
        print("❌ BOT_TOKEN не установлен или имеет значение по умолчанию!")
        print("   Получите токен у @BotFather в Telegram")
        return False
    
    print("✅ Файл .env найден и BOT_TOKEN установлен")
    return True

def check_dependencies():
    """Проверка установленных зависимостей"""
    required_modules = ['aiogram', 'asyncpg', 'pytz', 'dotenv']
    missing = []
    
    for module in required_modules:
        try:
            __import__(module)
        except ImportError:
            missing.append(module)
    
    if missing:
        print(f"❌ Отсутствуют модули: {', '.join(missing)}")
        print("   Установите зависимости: pip3 install -r requirements.txt")
        return False
    
    print("✅ Все зависимости установлены")
    return True

def check_postgresql():
    """Проверка подключения к PostgreSQL"""
    try:
        from dotenv import load_dotenv
        load_dotenv()
        
        import asyncpg
        import asyncio
        
        async def test_connection():
            try:
                db_host = os.getenv('DB_HOST')
                db_port = os.getenv('DB_PORT', '5432')
                db_user = os.getenv('DB_USER')
                db_password = os.getenv('DB_PASSWORD')
                
                if not all([db_host, db_port, db_user, db_password is not None]):
                    print("❌ Не все параметры подключения к БД установлены в .env")
                    return False
                
                conn = await asyncpg.connect(
                    host=db_host,
                    port=int(db_port),
                    user=db_user,
                    password=db_password,
                    database='postgres'  # Подключаемся к системной БД для проверки
                )
                await conn.close()
                return True
            except Exception as e:
                print(f"❌ Ошибка подключения к PostgreSQL: {e}")
                print("   Убедитесь, что:")
                print("   1. PostgreSQL запущен")
                print("   2. Данные для подключения в .env правильные")
                return False
        
        result = asyncio.run(test_connection())
        if result:
            print("✅ Подключение к PostgreSQL работает")
        return result
    except Exception as e:
        print(f"⚠️ Не удалось проверить PostgreSQL: {e}")
        return False

if __name__ == "__main__":
    print("Проверка настроек бота...\n")
    
    all_ok = True
    
    if not check_dependencies():
        all_ok = False
    
    print()
    
    if not check_env_file():
        all_ok = False
    
    print()
    
    if not check_postgresql():
        all_ok = False
    
    print()
    
    if all_ok:
        print("✅ Все проверки пройдены! Можно запускать бота: python3 main.py")
        sys.exit(0)
    else:
        print("❌ Найдены проблемы. Исправьте их перед запуском.")
        sys.exit(1)

