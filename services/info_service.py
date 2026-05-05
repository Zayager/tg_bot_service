"""Сервис для работы с информационными разделами"""
from typing import List, Optional, Dict
from database import db

class InfoService:
    """Сервис для работы с информационными разделами (адрес, контакты и т.д.)"""
    
    @staticmethod
    async def get_info_section(key: str) -> Optional[Dict]:
        """Получить информационный раздел"""
        row = await db.fetchrow(
            "SELECT * FROM info_sections WHERE key = $1 AND is_active = TRUE",
            key
        )
        return dict(row) if row else None
    
    @staticmethod
    async def get_all_info_sections() -> List[Dict]:
        """Получить все активные информационные разделы"""
        rows = await db.fetch("""
            SELECT * FROM info_sections
            WHERE is_active = TRUE
            ORDER BY order_index, id
        """)
        return [dict(row) for row in rows]
    
    @staticmethod
    async def update_info_section(key: str, content: str):
        """Обновить содержание информационного раздела"""
        await db.execute("""
            UPDATE info_sections 
            SET content = $1, updated_at = CURRENT_TIMESTAMP
            WHERE key = $2
        """, content, key)
    
    @staticmethod
    async def get_faq() -> List[Dict]:
        """Получить все FAQ"""
        rows = await db.fetch("""
            SELECT * FROM faq
            WHERE is_active = TRUE
            ORDER BY order_index, id
        """)
        return [dict(row) for row in rows]
    
    @staticmethod
    async def add_faq(question: str, answer: str):
        """Добавить FAQ"""
        max_order = await db.fetchval(
            "SELECT COALESCE(MAX(order_index), 0) FROM faq"
        ) or 0
        
        await db.execute("""
            INSERT INTO faq (question, answer, order_index)
            VALUES ($1, $2, $3)
        """, question, answer, max_order + 1)


