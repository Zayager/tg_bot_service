"""Главный файл бота"""
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

from config import BOT_TOKEN, ADMIN_ID
from database import db
from migrations import create_tables
from middleware.error_handler import ErrorHandlerMiddleware
from handlers import client_handlers, admin_handlers, admin_masters_handlers

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """Основная функция запуска бота"""
    # Инициализация бота и диспетчера
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    
    # Подключение к базе данных
    await db.connect()
    
    # Создание таблиц
    try:
        await create_tables()
        logger.info("База данных инициализирована")
    except Exception as e:
        logger.error(f"Ошибка при создании таблиц: {e}")
        # Отправляем ошибку администратору
        try:
            await bot.send_message(
                ADMIN_ID,
                f"❌ <b>Ошибка инициализации БД:</b>\n\n{str(e)}",
                parse_mode=ParseMode.HTML
            )
        except:
            pass
    
    # Регистрация middleware
    dp.message.middleware(ErrorHandlerMiddleware(bot))
    dp.callback_query.middleware(ErrorHandlerMiddleware(bot))
    
    # Регистрация роутеров
    dp.include_router(client_handlers.router)
    dp.include_router(admin_handlers.router)
    dp.include_router(admin_masters_handlers.router)
    
    # Запуск фонового процесса для напоминаний
    from services.reminder_service import reminder_worker
    asyncio.create_task(reminder_worker(bot))
    
    # Установка пользователя с ADMIN_ID как администратора
    try:
        from services.user_service import UserService
        user = await UserService.get_or_create_user(
            telegram_id=ADMIN_ID,
            username=None,
            full_name="Администратор"
        )
        await db.execute(
            "UPDATE users SET is_admin = TRUE, is_master = TRUE WHERE telegram_id = $1",
            ADMIN_ID
        )
        logger.info(f"Пользователь {ADMIN_ID} установлен как администратор")
    except Exception as e:
        logger.error(f"Ошибка при установке администратора: {e}")
    
    # Запуск бота
    try:
        logger.info("Бот запущен")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logger.error(f"Ошибка при запуске бота: {e}")
        raise
    finally:
        await db.disconnect()
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Бот остановлен пользователем")

