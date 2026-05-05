"""Сервис для работы с расписанием"""
from datetime import date, time, datetime, timedelta
from typing import List, Optional
from database import db
from models import Schedule
from utils.timezone import get_current_datetime_in_master_tz

DEFAULT_START = time(10, 0)
DEFAULT_END = time(21, 0)

class ScheduleService:
    """Сервис для работы с расписанием мастера"""

    @staticmethod
    def _default_schedule(schedule_date: date) -> Schedule:
        """Вернуть дефолтное расписание (10:00–21:00) для дат без записи в БД"""
        return Schedule(
            id=0,
            date=schedule_date,
            start_time=DEFAULT_START,
            end_time=DEFAULT_END,
            is_day_off=False,
        )

    @staticmethod
    async def get_schedule_for_date(schedule_date: date) -> Optional[Schedule]:
        """Получить расписание на конкретную дату.
        Если запись в БД отсутствует — возвращает дефолтное расписание (10:00–21:00)."""
        row = await db.fetchrow(
            "SELECT * FROM schedule WHERE date = $1",
            schedule_date
        )

        if not row:
            return ScheduleService._default_schedule(schedule_date)

        return Schedule(
            id=row['id'],
            date=row['date'],
            start_time=row['start_time'],
            end_time=row['end_time'],
            is_day_off=row['is_day_off'],
            created_at=row['created_at']
        )
    
    @staticmethod
    async def set_day_off(schedule_date: date):
        """Установить день как выходной"""
        await db.execute("""
            INSERT INTO schedule (date, is_day_off)
            VALUES ($1, TRUE)
            ON CONFLICT (date) DO UPDATE SET is_day_off = TRUE, start_time = NULL, end_time = NULL
        """, schedule_date)
    
    @staticmethod
    async def set_working_hours(schedule_date: date, start_time: time, end_time: time):
        """Установить рабочие часы на дату"""
        await db.execute("""
            INSERT INTO schedule (date, start_time, end_time, is_day_off)
            VALUES ($1, $2, $3, FALSE)
            ON CONFLICT (date) DO UPDATE 
            SET start_time = $2, end_time = $3, is_day_off = FALSE
        """, schedule_date, start_time, end_time)
    
    @staticmethod
    async def get_available_slots(
        schedule_date: date,
        duration_minutes: int,
        existing_appointments: Optional[List[datetime]] = None
    ) -> List[datetime]:
        """
        Получить доступные слоты времени на дату
        
        Args:
            schedule_date: Дата для поиска слотов
            duration_minutes: Длительность услуги в минутах
            existing_appointments: Список существующих записей на эту дату
        
        Returns:
            Список доступных datetime для записи
        """
        schedule = await ScheduleService.get_schedule_for_date(schedule_date)
        
        if schedule.is_day_off or not schedule.start_time or not schedule.end_time:
            return []
        
        existing_appointments = existing_appointments or []
        
        # Создаем список слотов
        slots = []
        current_time = datetime.combine(schedule_date, schedule.start_time)
        end_datetime = datetime.combine(schedule_date, schedule.end_time)
        
        slot_duration = timedelta(minutes=30)  # Базовый слот 30 минут
        
        while current_time + timedelta(minutes=duration_minutes) <= end_datetime:
            slot_end = current_time + timedelta(minutes=duration_minutes)
            
            # Проверяем, не пересекается ли слот с существующими записями
            is_available = True
            for appointment in existing_appointments:
                appointment_end = appointment + timedelta(minutes=60)  # Предполагаем длительность записи
                if (current_time < appointment_end and slot_end > appointment):
                    is_available = False
                    break
            
            if is_available:
                slots.append(current_time)
            
            current_time += slot_duration
        
        return slots
    
    @staticmethod
    async def get_schedule_for_month(year: int, month: int) -> List[Schedule]:
        """Получить расписание на месяц"""
        rows = await db.fetch("""
            SELECT * FROM schedule 
            WHERE EXTRACT(YEAR FROM date) = $1 AND EXTRACT(MONTH FROM date) = $2
            ORDER BY date
        """, year, month)
        
        return [
            Schedule(
                id=row['id'],
                date=row['date'],
                start_time=row['start_time'],
                end_time=row['end_time'],
                is_day_off=row['is_day_off'],
                created_at=row['created_at']
            )
            for row in rows
        ]
    
    @staticmethod
    async def is_date_available(appointment_date: datetime, duration_minutes: int) -> bool:
        """Проверить, доступна ли дата и время для записи"""
        schedule = await ScheduleService.get_schedule_for_date(appointment_date.date())
        
        if schedule.is_day_off or not schedule.start_time or not schedule.end_time:
            return False
        
        appointment_time = appointment_date.time()
        slot_end = (appointment_date + timedelta(minutes=duration_minutes)).time()
        
        # Проверяем, что время записи входит в рабочие часы
        if appointment_time < schedule.start_time:
            return False
        
        if slot_end > schedule.end_time:
            return False
        
        # Проверяем, нет ли пересечений с другими записями
        existing = await db.fetch("""
            SELECT appointment_date FROM appointments
            WHERE DATE(appointment_date) = $1
            AND status IN ('pending', 'confirmed')
        """, appointment_date.date())
        
        for row in existing:
            existing_start = row['appointment_date']
            existing_duration = await db.fetchval("""
                SELECT total_duration FROM appointments
                WHERE appointment_date = $1
            """, existing_start) or 60
            
            existing_end = existing_start + timedelta(minutes=existing_duration)
            
            # Проверяем пересечение
            if (appointment_date < existing_end and 
                appointment_date + timedelta(minutes=duration_minutes) > existing_start):
                return False
        
        return True
    
    # ─────────── Методы для расписания конкретного мастера ───────────

    @staticmethod
    async def get_master_schedule(master_id: int, schedule_date: date) -> Schedule:
        """Расписание мастера на дату. Если записи нет — 10:00–21:00."""
        row = await db.fetchrow(
            "SELECT * FROM master_schedule WHERE master_id = $1 AND date = $2",
            master_id, schedule_date
        )
        if not row:
            return ScheduleService._default_schedule(schedule_date)
        return Schedule(
            id=row['id'],
            date=row['date'],
            start_time=row['start_time'],
            end_time=row['end_time'],
            is_day_off=row['is_day_off'],
        )

    @staticmethod
    async def get_working_masters(department_id: int, schedule_date: date,
                                   service_id: Optional[int] = None) -> list:
        """Список активных мастеров отдела, которые работают в этот день
        и (если указан service_id) могут оказывать данную услугу."""
        masters = await db.fetch("""
            SELECT m.* FROM masters m
            WHERE m.department_id = $1 AND m.is_active = TRUE
            ORDER BY m.order_index, m.name
        """, department_id)

        # Если у услуги задан белый список — загружаем его один раз
        allowed_ids: Optional[List[int]] = None
        if service_id is not None:
            from services.service_service import ServiceService
            allowed = await ServiceService.get_masters_for_service(service_id)
            if allowed:  # пустой список = ограничений нет
                allowed_ids = allowed

        working = []
        for m in masters:
            if allowed_ids is not None and m['id'] not in allowed_ids:
                continue
            sched = await ScheduleService.get_master_schedule(m['id'], schedule_date)
            if not sched.is_day_off and sched.start_time and sched.end_time:
                working.append(dict(m))
        return working

    @staticmethod
    async def is_master_available(master_id: int, appointment_dt: datetime,
                                   duration_minutes: int) -> bool:
        """Проверяет, что мастер свободен в указанное время."""
        sched = await ScheduleService.get_master_schedule(master_id, appointment_dt.date())
        if sched.is_day_off or not sched.start_time or not sched.end_time:
            return False

        appt_time = appointment_dt.time()
        end_time = (appointment_dt + timedelta(minutes=duration_minutes)).time()
        if appt_time < sched.start_time or end_time > sched.end_time:
            return False

        existing = await db.fetch("""
            SELECT appointment_date, total_duration FROM appointments
            WHERE master_id = $1
              AND DATE(appointment_date) = $2
              AND status IN ('pending', 'confirmed')
        """, master_id, appointment_dt.date())

        slot_end = appointment_dt + timedelta(minutes=duration_minutes)
        for row in existing:
            ex_start = row['appointment_date']
            ex_end = ex_start + timedelta(minutes=row['total_duration'] or 60)
            if appointment_dt < ex_end and slot_end > ex_start:
                return False
        return True

    @staticmethod
    async def get_master_available_slots(
        master_id: int,
        schedule_date: date,
        duration_minutes: int,
        step_minutes: int = 30
    ) -> List[time]:
        """Вернуть список свободных слотов мастера на дату.
        Шаг слота — step_minutes (по умолчанию 30 мин).
        Прошедшие слоты сегодняшнего дня не включаются."""
        sched = await ScheduleService.get_master_schedule(master_id, schedule_date)
        if sched.is_day_off or not sched.start_time or not sched.end_time:
            return []

        existing = await db.fetch("""
            SELECT appointment_date, total_duration FROM appointments
            WHERE master_id = $1
              AND DATE(appointment_date) = $2
              AND status IN ('pending', 'confirmed')
        """, master_id, schedule_date)

        now = get_current_datetime_in_master_tz()
        step = timedelta(minutes=step_minutes)
        current = datetime.combine(schedule_date, sched.start_time)
        end = datetime.combine(schedule_date, sched.end_time)

        slots: List[time] = []
        while current + timedelta(minutes=duration_minutes) <= end:
            # Пропускаем прошедшие слоты если выбранная дата — сегодня
            if schedule_date == now.date() and current <= now.replace(tzinfo=None):
                current += step
                continue

            slot_end = current + timedelta(minutes=duration_minutes)
            available = True
            for row in existing:
                ex_start = row['appointment_date']
                ex_end = ex_start + timedelta(minutes=(row['total_duration'] or 60))
                if current < ex_end and slot_end > ex_start:
                    available = False
                    break

            if available:
                slots.append(current.time())
            current += step

        return slots

    @staticmethod
    async def is_date_fully_booked(schedule_date: date) -> bool:
        """Проверить, полностью ли занят день (нет свободных слотов)"""
        schedule = await ScheduleService.get_schedule_for_date(schedule_date)
        
        if schedule.is_day_off or not schedule.start_time or not schedule.end_time:
            return True
        
        # Получаем все записи на эту дату
        appointments = await db.fetch("""
            SELECT appointment_date, total_duration
            FROM appointments
            WHERE DATE(appointment_date) = $1
            AND status IN ('pending', 'confirmed')
        """, schedule_date)
        
        # Получаем доступные слоты для минимальной услуги (30 минут)
        from datetime import datetime, timedelta
        existing_times = [row['appointment_date'] for row in appointments]
        available_slots = await ScheduleService.get_available_slots(
            schedule_date,
            30,  # Минимальная длительность
            existing_times
        )
        
        return len(available_slots) == 0


