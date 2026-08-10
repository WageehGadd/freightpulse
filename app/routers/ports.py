from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.ports import PORT_REFERENCE
from app.database import get_db
from app.models import PortCongestion
from app.schemas.port import (
    PortCongestionMapResponse,
    PortCongestionResponse,
    PortMapEntry,
)

router = APIRouter()


@router.get("/ports/congestion-map", response_model=PortCongestionMapResponse)
async def get_congestion_map(db: AsyncSession = Depends(get_db)):
    latest_per_port_subq = (
        select(
            PortCongestion.port_code,
            func.max(PortCongestion.measured_at).label("max_measured_at"),
        )
        .group_by(PortCongestion.port_code)
        .subquery()
    )

    stmt = select(PortCongestion).join(
        latest_per_port_subq,
        (PortCongestion.port_code == latest_per_port_subq.c.port_code)
        & (PortCongestion.measured_at == latest_per_port_subq.c.max_measured_at),
    )
    result = await db.execute(stmt)
    ports = result.scalars().all()

    return PortCongestionMapResponse(
        ports=[
            PortMapEntry(
                port_code=p.port_code,
                port_name=p.port_name,
                latitude=PORT_REFERENCE.get(p.port_code, {}).get("latitude"),
                longitude=PORT_REFERENCE.get(p.port_code, {}).get("longitude"),
                congestion_index=p.congestion_index,
                severity=p.severity,
            )
            for p in ports
        ]
    )


@router.get("/ports/{code}/congestion", response_model=PortCongestionResponse)
async def get_port_congestion(code: str, db: AsyncSession = Depends(get_db)):
    stmt = (
        select(PortCongestion)
        .where(PortCongestion.port_code == code.upper())
        .order_by(PortCongestion.measured_at.desc())
        .limit(1)
    )
    port = (await db.execute(stmt)).scalar_one_or_none()

    if not port:
        raise HTTPException(status_code=404, detail=f"No congestion data found for port '{code}'")

    return PortCongestionResponse(
        port_code=port.port_code,
        port_name=port.port_name,
        congestion_index=port.congestion_index,
        avg_dwell_days=port.avg_dwell_days,
        vessels_waiting=port.vessels_waiting,
        severity=port.severity,
        advisory_text=port.advisory_text,
        measured_at=port.measured_at,
    )