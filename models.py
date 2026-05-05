"""Модели базы данных"""
from datetime import datetime, time
from typing import Optional

class Department:
    def __init__(self, id: int, name: str, order_index: int = 0, is_active: bool = True):
        self.id = id
        self.name = name
        self.order_index = order_index
        self.is_active = is_active


class Master:
    def __init__(self, id: int, name: str, department_id: Optional[int] = None,
                 is_active: bool = True, order_index: int = 0):
        self.id = id
        self.name = name
        self.department_id = department_id
        self.is_active = is_active
        self.order_index = order_index


class User:
    """Модель пользователя"""
    def __init__(
        self,
        id: int,
        telegram_id: int,
        username: Optional[str] = None,
        full_name: Optional[str] = None,
        is_admin: bool = False,
        is_master: bool = False,
        timezone: Optional[str] = None,
        created_at: Optional[datetime] = None
    ):
        self.id = id
        self.telegram_id = telegram_id
        self.username = username
        self.full_name = full_name
        self.is_admin = is_admin
        self.is_master = is_master
        self.timezone = timezone
        self.created_at = created_at or datetime.utcnow()

class Service:
    """Модель услуги"""
    def __init__(
        self,
        id: int,
        name: str,
        price: float,
        duration_minutes: int,
        description: Optional[str] = None,
        is_active: bool = True,
        is_additional: bool = False,
        order_index: int = 0,
        department_id: Optional[int] = None,
        category: Optional[str] = None,
        created_at: Optional[datetime] = None
    ):
        self.id = id
        self.name = name
        self.description = description
        self.price = price
        self.duration_minutes = duration_minutes
        self.is_active = is_active
        self.is_additional = is_additional
        self.order_index = order_index
        self.department_id = department_id
        self.category = category
        self.created_at = created_at or datetime.utcnow()

class Schedule:
    """Модель расписания мастера"""
    def __init__(
        self,
        id: int,
        date: datetime,
        start_time: Optional[time] = None,
        end_time: Optional[time] = None,
        is_day_off: bool = False,
        created_at: Optional[datetime] = None
    ):
        self.id = id
        self.date = date
        self.start_time = start_time
        self.end_time = end_time
        self.is_day_off = is_day_off
        self.created_at = created_at or datetime.utcnow()

class Appointment:
    """Модель записи"""
    def __init__(
        self,
        id: int,
        client_id: int,
        service_id: int,
        appointment_date: datetime,
        status: str = 'pending',  # pending, confirmed, cancelled, completed, no_show, moved
        total_price: float = 0.0,
        total_duration: int = 0,
        admin_comment: Optional[str] = None,
        client_note: Optional[str] = None,
        master_id: Optional[int] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None
    ):
        self.id = id
        self.client_id = client_id
        self.service_id = service_id
        self.appointment_date = appointment_date
        self.status = status
        self.total_price = total_price
        self.total_duration = total_duration
        self.admin_comment = admin_comment
        self.client_note = client_note
        self.master_id = master_id
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

class Client:
    """Модель клиента (расширенная информация)"""
    def __init__(
        self,
        id: int,
        user_id: int,
        phone: Optional[str] = None,
        notes: Optional[str] = None,
        created_at: Optional[datetime] = None
    ):
        self.id = id
        self.user_id = user_id
        self.phone = phone
        self.notes = notes
        self.created_at = created_at or datetime.utcnow()

class BotSettings:
    """Модель настроек бота (кастомизация текстов и кнопок)"""
    def __init__(
        self,
        id: int,
        key: str,
        value: str,
        type: str = 'text',  # text, button, order
        is_hidden: bool = False,
        order_index: int = 0,
        updated_at: Optional[datetime] = None
    ):
        self.id = id
        self.key = key
        self.value = value
        self.type = type
        self.is_hidden = is_hidden
        self.order_index = order_index
        self.updated_at = updated_at or datetime.utcnow()

