"""Сервис для работы с услугами"""
from typing import List, Optional
from database import db
from models import Service

class ServiceService:
    """Сервис для работы с услугами"""
    
    @staticmethod
    async def get_all_services(only_active: bool = True, only_main: bool = False) -> List[Service]:
        """Получить все услуги"""
        query = "SELECT * FROM services"
        conditions = []
        if only_active:
            conditions.append("is_active = TRUE")
        if only_main:
            conditions.append("(is_additional = FALSE OR is_additional IS NULL)")
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY order_index, id"
        
        rows = await db.fetch(query)
        return [
            Service(
                id=row['id'],
                name=row['name'],
                description=row['description'],
                price=float(row['price']),
                duration_minutes=row['duration_minutes'],
                is_active=row['is_active'],
                is_additional=row.get('is_additional', False),
                order_index=row['order_index'],
                department_id=row.get('department_id'),
                category=row.get('category'),
                created_at=row['created_at']
            )
            for row in rows
        ]
    
    @staticmethod
    async def get_service(service_id: int) -> Optional[Service]:
        """Получить услугу по ID"""
        row = await db.fetchrow("SELECT * FROM services WHERE id = $1", service_id)
        if not row:
            return None
        
        return Service(
            id=row['id'],
            name=row['name'],
            description=row['description'],
            price=float(row['price']),
            duration_minutes=row['duration_minutes'],
            is_active=row['is_active'],
            is_additional=row.get('is_additional', False),
            order_index=row['order_index'],
            department_id=row.get('department_id'),
            created_at=row['created_at']
        )
    
    @staticmethod
    async def create_service(
        name: str,
        price: float,
        duration_minutes: int,
        description: Optional[str] = None,
        is_additional: bool = False
    ) -> Service:
        """Создать новую услугу"""
        # Получаем максимальный order_index
        max_order = await db.fetchval(
            "SELECT COALESCE(MAX(order_index), 0) FROM services"
        ) or 0
        
        service_id = await db.fetchval(
            """
            INSERT INTO services (name, description, price, duration_minutes, order_index, is_additional)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
            """,
            name, description, price, duration_minutes, max_order + 1, is_additional
        )
        
        return await ServiceService.get_service(service_id)
    
    @staticmethod
    async def update_service(
        service_id: int,
        name: Optional[str] = None,
        description: Optional[str] = None,
        price: Optional[float] = None,
        duration_minutes: Optional[int] = None,
        is_active: Optional[bool] = None,
        is_additional: Optional[bool] = None,
        order_index: Optional[int] = None,
        department_id: Optional[int] = None,
        clear_department: bool = False
    ):
        """Обновить услугу"""
        updates = []
        params = []
        param_index = 1
        
        if name is not None:
            updates.append(f"name = ${param_index}")
            params.append(name)
            param_index += 1
        if description is not None:
            updates.append(f"description = ${param_index}")
            params.append(description)
            param_index += 1
        if price is not None:
            updates.append(f"price = ${param_index}")
            params.append(price)
            param_index += 1
        if duration_minutes is not None:
            updates.append(f"duration_minutes = ${param_index}")
            params.append(duration_minutes)
            param_index += 1
        if is_active is not None:
            updates.append(f"is_active = ${param_index}")
            params.append(is_active)
            param_index += 1
        if is_additional is not None:
            updates.append(f"is_additional = ${param_index}")
            params.append(is_additional)
            param_index += 1
        if order_index is not None:
            updates.append(f"order_index = ${param_index}")
            params.append(order_index)
            param_index += 1
        if clear_department:
            updates.append("department_id = NULL")
        elif department_id is not None:
            updates.append(f"department_id = ${param_index}")
            params.append(department_id)
            param_index += 1
        
        if updates:
            params.append(service_id)
            await db.execute(
                f"UPDATE services SET {', '.join(updates)} WHERE id = ${param_index}",
                *params
            )
    
    @staticmethod
    async def delete_service(service_id: int):
        """Удалить услугу (пометить как неактивную)"""
        await db.execute(
            "UPDATE services SET is_active = FALSE WHERE id = $1",
            service_id
        )

    # ─────────── Управление мастерами для услуги ───────────

    @staticmethod
    async def get_masters_for_service(service_id: int) -> List[int]:
        """Вернуть список master_id из белого списка услуги.
        Пустой список означает, что ограничений нет — услугу может делать любой мастер."""
        rows = await db.fetch(
            "SELECT master_id FROM master_services WHERE service_id = $1",
            service_id
        )
        return [row['master_id'] for row in rows]

    @staticmethod
    async def can_master_do_service(master_id: int, service_id: int) -> bool:
        """Может ли мастер оказывать услугу?
        True если белый список пуст (разрешено всем) или мастер в белом списке."""
        allowed = await ServiceService.get_masters_for_service(service_id)
        if not allowed:
            return True
        return master_id in allowed

    @staticmethod
    async def toggle_master_for_service(service_id: int, master_id: int) -> bool:
        """Добавить/убрать мастера из белого списка услуги.
        Возвращает True если мастер теперь добавлен, False если убран."""
        existing = await db.fetchrow(
            "SELECT 1 FROM master_services WHERE service_id = $1 AND master_id = $2",
            service_id, master_id
        )
        if existing:
            await db.execute(
                "DELETE FROM master_services WHERE service_id = $1 AND master_id = $2",
                service_id, master_id
            )
            return False
        else:
            await db.execute(
                "INSERT INTO master_services (service_id, master_id) VALUES ($1, $2)",
                service_id, master_id
            )
            return True


