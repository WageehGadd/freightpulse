from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import CarrierAdvisory, FreightRate, PortCongestion, RateTrend


@dataclass(frozen=True)
class RouteBriefContext:
    advisories: str
    conditions: str


async def build_route_brief_context(
    session: AsyncSession,
    *,
    origin: str,
    destination: str,
    carrier: str,
    cargo_type: str,
) -> RouteBriefContext:
    """Build bounded, database-derived facts for the route-brief AI service."""
    lane = f"{origin}-{destination}"

    advisories = (
        await session.execute(
            select(CarrierAdvisory)
            .where(
                CarrierAdvisory.carrier == carrier,
                CarrierAdvisory.affected_lanes.any(lane),
            )
            .order_by(CarrierAdvisory.published_at.desc())
            .limit(5)
        )
    ).scalars().all()
    if not advisories:
        advisories = (
            await session.execute(
                select(CarrierAdvisory)
                .where(CarrierAdvisory.carrier == carrier)
                .order_by(CarrierAdvisory.published_at.desc())
                .limit(5)
            )
        ).scalars().all()

    latest_rate = (
        await session.execute(
            select(FreightRate)
            .where(
                FreightRate.trade_lane == lane,
                FreightRate.container_type == cargo_type,
            )
            .order_by(FreightRate.rate_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    latest_trend = (
        await session.execute(
            select(RateTrend)
            .where(RateTrend.trade_lane == lane)
            .order_by(RateTrend.computed_date.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    ports = (
        await session.execute(
            select(PortCongestion)
            .where(
                or_(
                    PortCongestion.port_name.in_([origin, destination]),
                    PortCongestion.port_code.in_([origin, destination]),
                )
            )
            .order_by(PortCongestion.measured_at.desc())
            .limit(4)
        )
    ).scalars().all()

    advisory_lines = [
        " | ".join(
            part
            for part in (
                advisory.title,
                advisory.summary,
                f"effective {advisory.effective_date}" if advisory.effective_date else None,
                f"severity {advisory.impact_severity}" if advisory.impact_severity else None,
            )
            if part
        )
        for advisory in advisories
    ]
    condition_lines: list[str] = []
    if latest_rate:
        condition_lines.append(
            f"Latest {latest_rate.container_type} rate for {latest_rate.trade_lane}: "
            f"{latest_rate.rate_usd} USD on {latest_rate.rate_date}."
        )
    if latest_trend:
        condition_lines.append(
            f"Latest trend for {latest_trend.trade_lane}: {latest_trend.trend}; "
            f"7d change {latest_trend.change_7d_pct}; 30d change {latest_trend.change_30d_pct}."
        )
    condition_lines.extend(
        " | ".join(
            part
            for part in (
                port.port_name,
                f"severity {port.severity}" if port.severity else None,
                f"dwell {port.avg_dwell_days} days" if port.avg_dwell_days is not None else None,
                port.advisory_text,
            )
            if part
        )
        for port in ports
    )

    return RouteBriefContext(
        advisories="\n".join(advisory_lines),
        conditions="\n".join(condition_lines),
    )
