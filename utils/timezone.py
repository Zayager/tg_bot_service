"""Утилиты для работы с часовыми поясами"""
import pytz
from datetime import datetime, timezone
from typing import Optional

def get_master_timezone() -> pytz.BaseTzInfo:
    """Получить часовой пояс мастера"""
    from config import MASTER_TIMEZONE
    return pytz.timezone(MASTER_TIMEZONE)

def convert_to_master_timezone(dt: datetime, user_tz: Optional[str] = None) -> datetime:
    """
    Конвертировать datetime в часовой пояс мастера
    
    Args:
        dt: datetime для конвертации
        user_tz: часовой пояс пользователя (если известен)
    
    Returns:
        datetime в часовом поясе мастера
    """
    master_tz = get_master_timezone()
    
    # Если datetime наивный (без timezone), считаем что он уже в timezone мастера
    if dt.tzinfo is None:
        dt = master_tz.localize(dt)
    
    # Конвертируем в часовой пояс мастера
    return dt.astimezone(master_tz)

def format_datetime(dt: datetime, format: str = "%d.%m.%Y %H:%M") -> str:
    """Форматировать datetime в строку с учетом часового пояса мастера"""
    master_dt = convert_to_master_timezone(dt)
    return master_dt.strftime(format)

def format_date(dt: datetime, format: str = "%d.%m.%Y") -> str:
    """Форматировать дату в строку"""
    master_dt = convert_to_master_timezone(dt)
    return master_dt.strftime(format)

def format_time(dt: datetime, format: str = "%H:%M") -> str:
    """Форматировать время в строку"""
    master_dt = convert_to_master_timezone(dt)
    return master_dt.strftime(format)

def get_current_datetime_in_master_tz() -> datetime:
    """Получить текущее время в часовом поясе мастера"""
    master_tz = get_master_timezone()
    return datetime.now(master_tz)


