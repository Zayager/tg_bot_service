"""Сервис для работы с настройками бота"""
from typing import Optional, Dict, List
from database import db

class BotSettingsService:
    """Сервис для работы с настройками бота (кастомизация)"""
    
    @staticmethod
    async def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
        """Получить настройку по ключу"""
        row = await db.fetchrow(
            "SELECT value FROM bot_settings WHERE key = $1 AND is_hidden = FALSE",
            key
        )
        return row['value'] if row else default
    
    @staticmethod
    async def set_setting(key: str, value: str, setting_type: str = 'text'):
        """Установить настройку"""
        await db.execute("""
            INSERT INTO bot_settings (key, value, type)
            VALUES ($1, $2, $3)
            ON CONFLICT (key) DO UPDATE SET value = $2, type = $3, updated_at = CURRENT_TIMESTAMP
        """, key, value, setting_type)
    
    @staticmethod
    async def hide_setting(key: str):
        """Скрыть настройку (кнопку)"""
        await db.execute(
            "UPDATE bot_settings SET is_hidden = TRUE WHERE key = $1",
            key
        )
    
    @staticmethod
    async def show_setting(key: str):
        """Показать скрытую настройку (кнопку)"""
        await db.execute(
            "UPDATE bot_settings SET is_hidden = FALSE WHERE key = $1",
            key
        )
    
    @staticmethod
    async def set_order(key: str, order_index: int):
        """Установить порядок настройки"""
        await db.execute(
            "UPDATE bot_settings SET order_index = $1 WHERE key = $2",
            order_index, key
        )
    
    @staticmethod
    async def get_all_visible_settings() -> List[Dict]:
        """Получить все видимые настройки, отсортированные по order_index"""
        rows = await db.fetch("""
            SELECT * FROM bot_settings
            WHERE is_hidden = FALSE
            ORDER BY order_index, id
        """)
        
        return [dict(row) for row in rows]
    
    @staticmethod
    async def get_appointment_settings() -> Dict:
        """Получить настройки подтверждения записей"""
        row = await db.fetchrow("SELECT * FROM appointment_settings WHERE id = 1")
        if not row:
            return {
                'require_confirmation': False,
                'reminder_24h_enabled': True,
                'reminder_1_2h_enabled': True,
                'reminder_interval_hours': 2
            }
        
        return {
            'require_confirmation': row['require_confirmation'],
            'reminder_24h_enabled': row['reminder_24h_enabled'],
            'reminder_1_2h_enabled': row['reminder_1_2h_enabled'],
            'reminder_interval_hours': row['reminder_interval_hours']
        }
    
    @staticmethod
    async def update_appointment_settings(
        require_confirmation: Optional[bool] = None,
        reminder_24h_enabled: Optional[bool] = None,
        reminder_1_2h_enabled: Optional[bool] = None,
        reminder_interval_hours: Optional[int] = None
    ):
        """Обновить настройки подтверждения записей"""
        updates = []
        params = []
        param_index = 1
        
        if require_confirmation is not None:
            updates.append(f"require_confirmation = ${param_index}")
            params.append(require_confirmation)
            param_index += 1
        
        if reminder_24h_enabled is not None:
            updates.append(f"reminder_24h_enabled = ${param_index}")
            params.append(reminder_24h_enabled)
            param_index += 1
        
        if reminder_1_2h_enabled is not None:
            updates.append(f"reminder_1_2h_enabled = ${param_index}")
            params.append(reminder_1_2h_enabled)
            param_index += 1
        
        if reminder_interval_hours is not None:
            updates.append(f"reminder_interval_hours = ${param_index}")
            params.append(reminder_interval_hours)
            param_index += 1
        
        if updates:
            updates.append(f"updated_at = CURRENT_TIMESTAMP")
            await db.execute(
                f"UPDATE appointment_settings SET {', '.join(updates)} WHERE id = 1",
                *params
            )


