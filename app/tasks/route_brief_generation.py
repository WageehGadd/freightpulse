import asyncio
import uuid
import structlog
from sqlalchemy import select
from app.celery_app import celery_app
from app.database import AsyncSessionLocal
from app.models.route_brief import RouteBrief
from app.models.carrier_advisory import CarrierAdvisory
from app.models.freight_rate import FreightRate
from app.models.rate_trend import RateTrend
from app.models.port_congestion import PortCongestion
from app.ai.route_brief_generator import RouteBriefGenerator
from app.services.pdf_generator import generate_route_brief_pdf

logger = structlog.get_logger()


async def generate_route_brief_async(
    brief_id_str: str,
    session_factory=None,
    generator_factory=None,
    mark_failed_on_error: bool = True,
) -> dict:
    brief_uuid = uuid.UUID(brief_id_str)
    session_maker = session_factory or AsyncSessionLocal

    async with session_maker() as session:
        brief = await session.get(RouteBrief, brief_uuid)
        if brief is None:
            raise ValueError(f"RouteBrief '{brief_id_str}' not found")

        generator = generator_factory() if generator_factory else RouteBriefGenerator()

        try:
            # Gather context from DB
            lane = f"{brief.origin}-{brief.destination}"

            # 1. Advisories
            adv_stmt = select(CarrierAdvisory).limit(5)
            advisories_rows = (await session.execute(adv_stmt)).scalars().all()
            adv_summary = "; ".join([f"{a.carrier}: {a.summary or a.title}" for a in advisories_rows]) or "No active carrier advisories reported."

            # 2. Rate Trend & Port Congestion
            trend_stmt = select(RateTrend).where(RateTrend.trade_lane == lane).order_by(RateTrend.computed_date.desc()).limit(1)
            trend_row = (await session.execute(trend_stmt)).scalar_one_or_none()

            rate_stmt = select(FreightRate).where(FreightRate.trade_lane == lane).order_by(FreightRate.rate_date.desc()).limit(1)
            rate_row = (await session.execute(rate_stmt)).scalar_one_or_none()

            port_stmt = select(PortCongestion).where(PortCongestion.port_name.ilike(f"%{brief.origin}%")).limit(1)
            port_row = (await session.execute(port_stmt)).scalar_one_or_none()

            conditions = (
                f"Latest Rate: ${float(rate_row.rate_usd) if rate_row else 2000.0}/TEU, "
                f"Trend: {trend_row.trend if trend_row else 'stable'}, "
                f"Port Origin: {port_row.port_name if port_row else brief.origin} (Congestion: {port_row.congestion_index if port_row else 'Normal'})"
            )

            # Generate brief using AI generator
            output = await generator.generate_brief(
                origin=brief.origin,
                destination=brief.destination,
                carrier=brief.carrier or "All Available",
                advisories=adv_summary,
                conditions=conditions,
            )

            # Generate PDF file
            pdf_path = generate_route_brief_pdf(
                brief_id=str(brief.id),
                origin=brief.origin,
                destination=brief.destination,
                carrier=brief.carrier,
                cargo_type=brief.cargo_type,
                recommendation=output.recommendation,
                risk_level=output.risk_level,
                brief_markdown=output.brief_markdown,
            )

            brief.brief_markdown = output.brief_markdown
            brief.recommendation = output.recommendation
            brief.risk_level = output.risk_level
            brief.pdf_path = pdf_path
            brief.status = "completed"
            brief.error_message = None
            await session.commit()

            return {
                "brief_id": str(brief_uuid),
                "status": "completed",
                "pdf_path": pdf_path,
            }

        except Exception as exc:
            if mark_failed_on_error:
                brief.status = "failed"
                brief.error_message = "Route brief generation failed. Please try again later."
                brief.pdf_path = None
                await session.commit()
            logger.exception("route_brief_generation_failed", brief_id=str(brief_uuid), error=str(exc))
            raise


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def generate_route_brief(self, brief_id: str):
    try:
        return asyncio.run(generate_route_brief_async(brief_id))
    except Exception as exc:
        raise self.retry(exc=exc) from exc
