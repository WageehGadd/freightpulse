
import asyncio
import random
from datetime import date, datetime, timedelta, timezone

from app.database import AsyncSessionLocal
from app.models import (
    CarrierAdvisory,
    FreightRate,
    PortCongestion,
    RateTrend,
)

TRADE_LANES = [
    ("Egypt-China", "Port Said", "China"),
    ("Egypt-Europe", "Port Said", "Europe"),
    ("UAE-Asia", "Jebel Ali", "Asia"),
    ("UAE-Europe", "Jebel Ali", "Europe"),
]


PORTS = [
    ("EGPSD", "Port Said", 45.0, 1.2, 8, "normal"),
    ("EGALY", "Alexandria", 60.0, 2.1, 15, "elevated"),
    ("EGSKH", "Sokhna", 30.0, 0.8, 4, "normal"),
    ("AEJEA", "Jebel Ali", 78.0, 3.0, 22, "critical"),
    ("AEAUH", "Abu Dhabi", 40.0, 1.5, 6, "normal"),
    ("CNSHA", "Shanghai", 55.0, 1.8, 18, "elevated"),
]


async def seed_freight_rates(session):
    """Generate 30 days of realistic sample rate data for each trade lane."""
    today = datetime.now(timezone.utc).date()

    for lane, origin, dest_region in TRADE_LANES:
        base_rate = random.uniform(1800, 3200)

        for days_ago in range(30, -1, -1):
            rate_date = today - timedelta(days=days_ago)

            # Add small daily fluctuations around the base rate
            # to simulate realistic market data.
            drift = random.uniform(-50, 50)

            # Apply a slight downward trend over time.
            rate_usd = round(
                base_rate + drift + (days_ago * -2),
                2,
            )

            for container_type in ["20ft", "40ft"]:
                multiplier = (
                    1.0 if container_type == "40ft" else 0.65
                )

                session.add(
                    FreightRate(
                        source="SCFI",
                        trade_lane=lane,
                        origin_port=origin,
                        dest_region=dest_region,
                        container_type=container_type,
                        rate_usd=round(
                            rate_usd * multiplier,
                            2,
                        ),
                        rate_date=rate_date,
                        week_number=rate_date.isocalendar()[1],
                    )
                )

    await session.commit()

    print(
        f"Seeded freight_rates for "
        f"{len(TRADE_LANES)} lanes x 31 days x 2 container types"
    )


async def seed_rate_trends(session):
    """
    Generate one precomputed trend row for each trade lane.
    This is sample data and is not calculated from actual rate history.
    """
    today = datetime.now(timezone.utc).date()
    trends = ["rising", "stable", "falling"]

    for lane, _, _ in TRADE_LANES:
        trend = random.choice(trends)

        change_7d = (
            round(random.uniform(-5, 5), 2)
            if trend == "stable"
            else round(
                random.uniform(3, 15)
                * (1 if trend == "rising" else -1),
                2,
            )
        )

        change_30d = round(
            change_7d * random.uniform(1.5, 3),
            2,
        )

        session.add(
            RateTrend(
                trade_lane=lane,
                computed_date=today,
                avg_7d_usd=round(
                    random.uniform(1800, 3200),
                    2,
                ),
                avg_30d_usd=round(
                    random.uniform(1800, 3200),
                    2,
                ),
                change_7d_pct=change_7d,
                change_30d_pct=change_30d,
                trend=trend,
                slope_per_week=round(
                    change_7d / 100,
                    3,
                ),
                anomaly_flag=abs(change_7d) > 12,
            )
        )

    await session.commit()

    print(
        f"Seeded rate_trends for {len(TRADE_LANES)} lanes"
    )


async def seed_port_congestion(session):
    for code, name, congestion, dwell, waiting, severity in PORTS:
        session.add(
            PortCongestion(
                port_code=code,
                port_name=name,
                congestion_index=congestion,
                avg_dwell_days=dwell,
                vessels_waiting=waiting,
                advisory_text=(
                    f"{name} operating at "
                    f"{severity} congestion levels."
                ),
                severity=severity,
                measured_at=datetime.now(timezone.utc),
                source="Port Authority Reports",
            )
        )

    await session.commit()

    print(
        f"Seeded port_congestion for {len(PORTS)} ports"
    )


async def seed_carrier_advisories(session):
    advisories = [
        (
            "MSC",
            "surcharge",
            "Peak Season Surcharge - Asia to Europe",
            "MSC announces PSS of $300/TEU effective for Asia-Europe lanes.",
            ["Egypt-Europe"],
            "high",
        ),
        (
            "Maersk",
            "route_suspension",
            "Temporary Suspension - Red Sea Routing",
            "Maersk suspends direct Red Sea routing, rerouting via Cape of Good Hope.",
            ["Egypt-Europe", "UAE-Europe"],
            "high",
        ),
        (
            "CMA CGM",
            "schedule_change",
            "Schedule Update - Shanghai Service",
            "CMA CGM adjusts weekly schedule for Shanghai-bound vessels by 2 days.",
            ["UAE-Asia", "Egypt-China"],
            "medium",
        ),
    ]

    for carrier, adv_type, title, summary, lanes, severity in advisories:
        session.add(
            CarrierAdvisory(
                carrier=carrier,
                advisory_type=adv_type,
                title=title,
                # These are explicitly pre-processed demo advisories; the
                # seeded source text is retained for model compatibility.
                raw_text=summary,
                summary=summary,
                affected_lanes=lanes,
                effective_date=datetime.now(timezone.utc).date() + timedelta(days=7),
                published_at=(
                    datetime.now(timezone.utc)
                    - timedelta(days=random.randint(0, 3))
                ),
                source_url=(
                    f"https://example.com/"
                    f"{carrier.lower().replace(' ', '')}/advisory"
                ),
            )
        )

    await session.commit()

    print(
        f"Seeded carrier_advisories: {len(advisories)} entries"
    )


async def main():
    async with AsyncSessionLocal() as session:
        print("Seeding database...\n")

        await seed_freight_rates(session)
        await seed_rate_trends(session)
        await seed_port_congestion(session)
        await seed_carrier_advisories(session)

        print("\nSeeding completed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
