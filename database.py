"""Модуль для работы с базой данных"""
import asyncpg
import logging
from typing import Optional

logger = logging.getLogger(__name__)

class Database:
    """Класс для управления подключением к базе данных"""
    
    def __init__(self):
        self.pool: Optional[asyncpg.Pool] = None
    
    async def connect(self):
        """Создание пула подключений"""
        try:
            # Парсим DATABASE_URL для обработки пустого пароля
            from config import DB_USER, DB_PASSWORD, DB_HOST, DB_PORT, DB_NAME
            password = DB_PASSWORD if DB_PASSWORD else None
            self.pool = await asyncpg.create_pool(
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USER,
                password=password,
                database=DB_NAME,
                min_size=1,
                max_size=10,
                command_timeout=60
            )
            logger.info("База данных подключена")
        except Exception as e:
            logger.error(f"Ошибка подключения к базе данных: {e}")
            raise
    
    async def disconnect(self):
        """Закрытие пула подключений"""
        if self.pool:
            await self.pool.close()
            logger.info("Подключение к базе данных закрыто")
    
    async def execute(self, query: str, *args):
        """Выполнение запроса без возврата результата"""
        async with self.pool.acquire() as connection:
            await connection.execute(query, *args)
    
    async def fetch(self, query: str, *args):
        """Выполнение запроса с возвратом всех строк"""
        async with self.pool.acquire() as connection:
            return await connection.fetch(query, *args)
    
    async def fetchrow(self, query: str, *args):
        """Выполнение запроса с возвратом одной строки"""
        async with self.pool.acquire() as connection:
            return await connection.fetchrow(query, *args)
    
    async def fetchval(self, query: str, *args):
        """Выполнение запроса с возвратом одного значения"""
        async with self.pool.acquire() as connection:
            return await connection.fetchval(query, *args)

# Глобальный экземпляр базы данных
db = Database()

