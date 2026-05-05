"""Сервис для работы с записями"""
from datetime import datetime, timedelta, date
from typing import List, Optional
from database import db
from models import Appointment
from services.service_service import ServiceService

class AppointmentService:
    """Сервис для работы с записями"""
    
    @staticmethod
    async def create_appointment(
        client_id: int,
        service_id: int,
        appointment_date: datetime,
        additional_service_ids: Optional[List[int]] = None,
        client_note: Optional[str] = None,
        master_id: Optional[int] = None,
    ) -> Appointment:
        """Создать новую запись"""
        if additional_service_ids is None:
            additional_service_ids = []
        
        # Получаем информацию об услуге
        service = await ServiceService.get_service(service_id)
        if not service:
            raise ValueError("Услуга не найдена")
        
        # Рассчитываем общую стоимость и длительность
        total_price = service.price
        total_duration = service.duration_minutes
        
        for add_service_id in additional_service_ids:
            add_service = await ServiceService.get_service(add_service_id)
            if add_service:
                total_price += add_service.price
                total_duration += add_service.duration_minutes
        
        appointment_id = await db.fetchval("""
            INSERT INTO appointments (client_id, service_id, appointment_date,
                                      total_price, total_duration, status,
                                      client_note, master_id)
            VALUES ($1, $2, $3, $4, $5, 'pending', $6, $7)
            RETURNING id
        """, client_id, service_id, appointment_date,
             total_price, total_duration, client_note, master_id)
        
        # Добавляем дополнительные услуги
        for add_service_id in additional_service_ids:
            await db.execute("""
                INSERT INTO appointment_additional_services (appointment_id, service_id)
                VALUES ($1, $2)
            """, appointment_id, add_service_id)
        
        return await AppointmentService.get_appointment(appointment_id)
    
    @staticmethod
    async def get_appointment(appointment_id: int) -> Optional[Appointment]:
        """Получить запись по ID"""
        row = await db.fetchrow(
            "SELECT * FROM appointments WHERE id = $1",
            appointment_id
        )
        
        if not row:
            return None
        
        return Appointment(
            id=row['id'],
            client_id=row['client_id'],
            service_id=row['service_id'],
            appointment_date=row['appointment_date'],
            status=row['status'],
            total_price=float(row['total_price']),
            total_duration=row['total_duration'],
            admin_comment=row.get('admin_comment') if 'admin_comment' in row else None,
            client_note=row.get('client_note') if 'client_note' in row else None,
            master_id=row.get('master_id') if 'master_id' in row else None,
            created_at=row['created_at'],
            updated_at=row['updated_at'],
        )
    
    @staticmethod
    async def get_client_appointments(client_id: int, only_active: bool = True) -> List[Appointment]:
        """Получить все записи клиента"""
        query = "SELECT * FROM appointments WHERE client_id = $1"
        if only_active:
            query += " AND status IN ('pending', 'confirmed')"
        query += " ORDER BY appointment_date"
        
        rows = await db.fetch(query, client_id)
        
        return [
            Appointment(
                id=row['id'],
                client_id=row['client_id'],
                service_id=row['service_id'],
                appointment_date=row['appointment_date'],
                status=row['status'],
                total_price=float(row['total_price']),
                total_duration=row['total_duration'],
                created_at=row['created_at'],
                updated_at=row['updated_at']
            )
            for row in rows
        ]
    
    @staticmethod
    async def update_appointment(
        appointment_id: int,
        service_id: Optional[int] = None,
        appointment_date: Optional[datetime] = None,
        status: Optional[str] = None,
        admin_comment: Optional[str] = None,
        changed_by: Optional[int] = None
    ) -> Appointment:
        """Обновить запись"""
        # Получаем старую запись для истории
        old_appointment = await AppointmentService.get_appointment(appointment_id)
        if not old_appointment:
            raise ValueError("Запись не найдена")
        
        updates = []
        params = []
        param_index = 1
        change_type = None
        
        if service_id is not None and service_id != old_appointment.service_id:
            # Обновляем информацию об услуге
            service = await ServiceService.get_service(service_id)
            if service:
                updates.append(f"service_id = ${param_index}")
                params.append(service_id)
                param_index += 1
                updates.append(f"total_price = ${param_index}")
                params.append(service.price)
                param_index += 1
                updates.append(f"total_duration = ${param_index}")
                params.append(service.duration_minutes)
                param_index += 1
                change_type = 'service_changed'
        
        if appointment_date is not None and appointment_date != old_appointment.appointment_date:
            updates.append(f"appointment_date = ${param_index}")
            params.append(appointment_date)
            param_index += 1
            change_type = 'date_changed'
        
        if status is not None and status != old_appointment.status:
            updates.append(f"status = ${param_index}")
            params.append(status)
            param_index += 1
            change_type = 'status_changed'
        
        if admin_comment is not None and admin_comment != old_appointment.admin_comment:
            updates.append(f"admin_comment = ${param_index}")
            params.append(admin_comment)
            param_index += 1
            change_type = 'comment_changed'
        
        if updates:
            updates.append(f"updated_at = CURRENT_TIMESTAMP")
            params.append(appointment_id)
            await db.execute(
                f"UPDATE appointments SET {', '.join(updates)} WHERE id = ${param_index}",
                *params
            )
            
            # Записываем в историю только если были реальные изменения
            if change_type:
                change_reason = f"Изменение: {change_type}"
                if status is not None:
                    await db.execute("""
                        INSERT INTO appointments_history (appointment_id, old_status, new_status, changed_by, change_reason)
                        VALUES ($1, $2, $3, $4, $5)
                    """, appointment_id, old_appointment.status, status, changed_by, change_reason)
                else:
                    await db.execute("""
                        INSERT INTO appointments_history (appointment_id, changed_by, change_reason)
                        VALUES ($1, $2, $3)
                    """, appointment_id, changed_by, change_reason)
        
        return await AppointmentService.get_appointment(appointment_id)
    
    @staticmethod
    async def cancel_appointment(appointment_id: int, reason: Optional[str] = None):
        """Отменить запись"""
        await AppointmentService.update_appointment(appointment_id, status='cancelled')
        
        if reason:
            await db.execute("""
                UPDATE appointments_history
                SET change_reason = $1
                WHERE id = (
                    SELECT id FROM appointments_history
                    WHERE appointment_id = $2
                    ORDER BY created_at DESC
                    LIMIT 1
                )
            """, reason, appointment_id)
    
    @staticmethod
    async def get_appointments_for_date(appointment_date: date) -> List[Appointment]:
        """Получить все записи на дату"""
        rows = await db.fetch("""
            SELECT * FROM appointments
            WHERE DATE(appointment_date) = $1
            ORDER BY appointment_date
        """, appointment_date)
        
        return [
            Appointment(
                id=row['id'],
                client_id=row['client_id'],
                service_id=row['service_id'],
                appointment_date=row['appointment_date'],
                status=row['status'],
                total_price=float(row['total_price']),
                total_duration=row['total_duration'],
                created_at=row['created_at'],
                updated_at=row['updated_at']
            )
            for row in rows
        ]
    
    @staticmethod
    async def format_appointment_info(appointment: Appointment) -> str:
        """Форматировать информацию о записи для отправки клиенту"""
        from utils.timezone import format_datetime, format_date, format_time
        from services.service_service import ServiceService
        
        service = await ServiceService.get_service(appointment.service_id)
        service_name = service.name if service else "Неизвестная услуга"
        
        info = (
            f"📅 <b>Ваша запись</b>\n\n"
            f"Услуга: {service_name}\n"
            f"Дата: {format_date(appointment.appointment_date)}\n"
            f"Время: {format_time(appointment.appointment_date)}\n"
            f"Длительность: {appointment.total_duration} минут\n"
            f"Стоимость: {appointment.total_price:.2f} ₽\n"
            f"Статус: {AppointmentService._format_status(appointment.status)}"
        )
        if getattr(appointment, 'master_id', None):
            master_row = await db.fetchrow("SELECT name FROM masters WHERE id = $1",
                                           appointment.master_id)
            if master_row:
                info += f"\nМастер: {master_row['name']}"
        elif appointment.client_note:
            info += f"\nЖелаемый мастер: {appointment.client_note}"
        
        return info
    
    @staticmethod
    def _format_status(status: str) -> str:
        """Форматировать статус записи"""
        status_map = {
            'pending': '⏳ Ожидает подтверждения',
            'confirmed': '✅ Подтверждена',
            'cancelled': '❌ Отменена',
            'completed': '✓ Завершена',
            'no_show': '🚫 Не пришёл',
            'moved': '🔄 Перенесена'
        }
        return status_map.get(status, status)

