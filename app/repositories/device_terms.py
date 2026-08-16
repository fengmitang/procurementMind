from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_app.device_terms.schemas import DeviceTermSource
from app.models.procurement import PurchaseRequest
from app.schemas.procurement import DEVICE_PROFESSIONS


class DeviceTermRepository:
    async def list_distinct(self, session: AsyncSession) -> list[DeviceTermSource]:
        count = func.count(PurchaseRequest.request_id)
        result = await session.execute(
            select(
                PurchaseRequest.device_profession,
                PurchaseRequest.device_name,
                count.label("source_count"),
            )
            .where(
                PurchaseRequest.device_profession.in_(DEVICE_PROFESSIONS),
                PurchaseRequest.device_name.is_not(None),
                func.trim(PurchaseRequest.device_name) != "",
            )
            .group_by(PurchaseRequest.device_profession, PurchaseRequest.device_name)
            .order_by(PurchaseRequest.device_profession, PurchaseRequest.device_name)
        )
        return [
            DeviceTermSource(
                device_profession=profession,
                device_name=name,
                source_count=source_count,
            )
            for profession, name, source_count in result.all()
        ]
