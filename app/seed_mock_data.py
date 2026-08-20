import asyncio
import random
import uuid
from datetime import date, datetime, timedelta, timezone

from app.database import AsyncSessionLocal
from app.models import (
    FreightRate,
    PortCongestion,
    CarrierAdvisory,
    RateTrend,
    RouteBrief,
    RateAlert,
    RateAlertRule,
    User,
    ApiKey,
)


# ============================================================
# CONFIG
# ============================================================

RANDOM_SEED = 42
random.seed(RANDOM_SEED)

TODAY = date.today()
NOW = datetime.now(timezone.utc)


# ============================================================
# MOCK USERS
# ============================================================

MOCK_USERS = [
    {
        "email": "admin@freightpulse.test",
        "is_admin": True,
    },
    {
        "email": "demo@freightpulse.test",
        "is_admin": False,
    },
    {
        "email": "analyst@freightpulse.test",
        "is_admin": False,
    },
]


# ============================================================
# TRADE LANES
# ============================================================

TRADE_LANES = [
    {
        "trade_lane": "Egypt-China",
        "origin_port": "Port Said",
        "dest_region": "China",
        "base_rate": 2450,
    },
    {
        "trade_lane": "Egypt-Europe",
        "origin_port": "Port Said",
        "dest_region": "Europe",
        "base_rate": 2100,
    },
    {
        "trade_lane": "UAE-Asia",
        "origin_port": "Jebel Ali",
        "dest_region": "Asia",
        "base_rate": 2250,
    },
    {
        "trade_lane": "UAE-Europe",
        "origin_port": "Jebel Ali",
        "dest_region": "Europe",
        "base_rate": 2350,
    },
]


# ============================================================
# PORTS
# ============================================================

PORTS = [
    {
        "port_code": "EGPSD",
        "port_name": "Port Said",
        "congestion_index": 62.0,
        "avg_dwell_days": 3.2,
        "vessels_waiting": 14,
        "severity": "elevated",
        "advisory_text": (
            "Moderate congestion due to increased Suez Canal "
            "transit traffic."
        ),
    },
    {
        "port_code": "EGALY",
        "port_name": "Alexandria",
        "congestion_index": 48.0,
        "avg_dwell_days": 2.4,
        "vessels_waiting": 9,
        "severity": "normal",
        "advisory_text": (
            "Port operations are generally stable with minor delays."
        ),
    },
    {
        "port_code": "EGSKH",
        "port_name": "Sokhna",
        "congestion_index": 35.0,
        "avg_dwell_days": 1.7,
        "vessels_waiting": 5,
        "severity": "normal",
        "advisory_text": (
            "Normal operations with limited vessel waiting time."
        ),
    },
    {
        "port_code": "AEJEA",
        "port_name": "Jebel Ali",
        "congestion_index": 78.0,
        "avg_dwell_days": 4.5,
        "vessels_waiting": 23,
        "severity": "critical",
        "advisory_text": (
            "High congestion and extended dwell times due to "
            "elevated vessel traffic."
        ),
    },
    {
        "port_code": "AEAUH",
        "port_name": "Abu Dhabi",
        "congestion_index": 41.0,
        "avg_dwell_days": 1.9,
        "vessels_waiting": 7,
        "severity": "normal",
        "advisory_text": (
            "Port operations remain stable with normal vessel flow."
        ),
    },
    {
        "port_code": "CNSHA",
        "port_name": "Shanghai",
        "congestion_index": 55.0,
        "avg_dwell_days": 2.8,
        "vessels_waiting": 18,
        "severity": "elevated",
        "advisory_text": (
            "Elevated congestion caused by increased container volumes."
        ),
    },
]


# ============================================================
# CARRIER ADVISORIES
# ============================================================

ADVISORIES = [
    {
        "carrier": "CMA CGM",
        "advisory_type": "surcharge",
        "title": (
            "Middle East - Dangerous Goods Surcharge Implementation"
        ),
        "raw_text": (
            "CMA CGM announces implementation of a dangerous goods "
            "surcharge for selected Middle East trade lanes. "
            "The surcharge will apply to eligible shipments starting "
            "September 1, 2026."
        ),
        "summary": (
            "Dangerous goods surcharge applies to selected "
            "Middle East trade lanes."
        ),
        "impact_severity": "high",
        "affected_lanes": [
            "Egypt-Europe",
            "UAE-Europe",
        ],
        "effective_date": date(2026, 9, 1),
        "source_url": "https://www.cma-cgm.com/",
        "published_at": NOW - timedelta(days=3),
    },
    {
        "carrier": "CMA CGM",
        "advisory_type": "rate_update",
        "title": (
            "FAK Rates - Asia to Mediterranean and North Africa"
        ),
        "raw_text": (
            "CMA CGM announces updated FAK rates from Asia to "
            "the Mediterranean and North Africa for selected "
            "container types."
        ),
        "summary": (
            "Updated FAK rates announced for Asia to Mediterranean "
            "and North Africa services."
        ),
        "impact_severity": "medium",
        "affected_lanes": [
            "Egypt-China",
        ],
        "effective_date": date(2026, 8, 15),
        "source_url": "https://www.cma-cgm.com/",
        "published_at": NOW - timedelta(days=4),
    },
    {
        "carrier": "Maersk",
        "advisory_type": "route_suspension",
        "title": "Temporary Suspension - Red Sea Routing",
        "raw_text": (
            "Maersk temporarily suspends selected direct Red Sea "
            "routing and reroutes vessels via the Cape of Good Hope."
        ),
        "summary": (
            "Selected Red Sea services are temporarily rerouted "
            "via the Cape of Good Hope."
        ),
        "impact_severity": "high",
        "affected_lanes": [
            "Egypt-Europe",
            "UAE-Europe",
        ],
        "effective_date": date(2026, 8, 20),
        "source_url": "https://www.maersk.com/",
        "published_at": NOW - timedelta(days=1),
    },
    {
        "carrier": "Maersk",
        "advisory_type": "schedule_change",
        "title": "East-West Network - Port Said Rotation Change",
        "raw_text": (
            "Maersk adjusts the weekly vessel rotation for selected "
            "Port Said calls due to operational changes."
        ),
        "summary": (
            "Weekly Port Said rotation has been adjusted."
        ),
        "impact_severity": "medium",
        "affected_lanes": [
            "Egypt-Europe",
        ],
        "effective_date": date(2026, 8, 18),
        "source_url": "https://www.maersk.com/",
        "published_at": NOW - timedelta(hours=18),
    },
    {
        "carrier": "MSC",
        "advisory_type": "schedule_change",
        "title": "Schedule Update - Shanghai to Jebel Ali Service",
        "raw_text": (
            "MSC adjusts the weekly schedule for Shanghai to "
            "Jebel Ali services due to port congestion."
        ),
        "summary": (
            "Shanghai-Jebel Ali schedule adjusted due to congestion."
        ),
        "impact_severity": "medium",
        "affected_lanes": [
            "UAE-Asia",
            "Egypt-China",
        ],
        "effective_date": date(2026, 8, 25),
        "source_url": "https://www.msc.com/",
        "published_at": NOW - timedelta(hours=6),
    },
    {
        "carrier": "MSC",
        "advisory_type": "congestion",
        "title": "Jebel Ali Port Congestion Advisory",
        "raw_text": (
            "MSC advises customers of extended dwell times at "
            "Jebel Ali due to elevated vessel traffic."
        ),
        "summary": (
            "Extended dwell times reported at Jebel Ali."
        ),
        "impact_severity": "high",
        "affected_lanes": [
            "UAE-Asia",
            "UAE-Europe",
        ],
        "effective_date": date(2026, 8, 12),
        "source_url": "https://www.msc.com/",
        "published_at": NOW - timedelta(hours=2),
    },
]


# ============================================================
# HELPER
# ============================================================

def generate_rate(
    base_rate: float,
    days_ago: int,
    container_type: str,
) -> float:
    """
    Generate realistic-looking historical freight rates.
    """

    # Small market fluctuation
    fluctuation = random.uniform(-70, 70)

    # Slight trend over time
    trend = -days_ago * 2.5

    rate = base_rate + trend + fluctuation

    if container_type == "20ft":
        rate *= 0.65

    return round(max(rate, 500), 2)


# ============================================================
# SEED USERS
# ============================================================

async def seed_users(session):
    users = []

    for data in MOCK_USERS:
        user = User(
            id=uuid.uuid4(),
            email=data["email"],
            is_admin=data["is_admin"],
        )

        session.add(user)
        users.append(user)

    await session.flush()

    print(f"✓ Seeded {len(users)} users")

    return users


# ============================================================
# SEED FREIGHT RATES
# ============================================================

async def seed_freight_rates(session):
    count = 0

    for lane in TRADE_LANES:

        for days_ago in range(30, -1, -1):

            rate_date = TODAY - timedelta(days=days_ago)

            for container_type in ["20ft", "40ft"]:

                rate = generate_rate(
                    base_rate=lane["base_rate"],
                    days_ago=days_ago,
                    container_type=container_type,
                )

                session.add(
                    FreightRate(
                        id=uuid.uuid4(),
                        source="SCFI",
                        trade_lane=lane["trade_lane"],
                        origin_port=lane["origin_port"],
                        dest_region=lane["dest_region"],
                        container_type=container_type,
                        rate_usd=rate,
                        rate_date=rate_date,
                        week_number=rate_date.isocalendar().week,
                        source_url="https://www.scfi.com.cn/",
                    )
                )

                count += 1

    await session.flush()

    print(f"✓ Seeded {count} freight rates")


# ============================================================
# SEED RATE TRENDS
# ============================================================

async def seed_rate_trends(session):
    count = 0

    trend_config = {
        "Egypt-China": "rising",
        "Egypt-Europe": "stable",
        "UAE-Asia": "falling",
        "UAE-Europe": "rising",
    }

    for lane in TRADE_LANES:

        trade_lane = lane["trade_lane"]

        trend = trend_config.get(
            trade_lane,
            "stable",
        )

        if trend == "rising":
            change_7d = random.uniform(4, 10)
        elif trend == "falling":
            change_7d = random.uniform(-10, -4)
        else:
            change_7d = random.uniform(-2, 2)

        change_30d = change_7d * random.uniform(1.8, 2.8)

        avg_30d = lane["base_rate"] + random.uniform(-100, 100)
        avg_7d = avg_30d * (1 + change_7d / 100)

        session.add(
            RateTrend(
                id=uuid.uuid4(),
                trade_lane=trade_lane,
                computed_date=TODAY,
                avg_7d_usd=round(avg_7d, 2),
                avg_30d_usd=round(avg_30d, 2),
                change_7d_pct=round(change_7d, 2),
                change_30d_pct=round(change_30d, 2),
                trend=trend,
                slope_per_week=round(change_7d / 100, 4),
                r_squared=round(random.uniform(0.72, 0.94), 2),
                anomaly_flag=abs(change_7d) >= 8,
                status="completed",
                outlook_text=(
                    f"The {trade_lane} lane is currently showing "
                    f"a {trend} rate trend."
                ),
                recommendation=(
                    "Consider booking earlier to reduce exposure."
                    if trend == "rising"
                    else "Monitor market conditions before booking."
                    if trend == "stable"
                    else "Consider reviewing current market rates."
                ),
                confidence=random.randint(72, 94),
            )
        )

        count += 1

    await session.flush()

    print(f"✓ Seeded {count} rate trends")


# ============================================================
# SEED PORT CONGESTION
# ============================================================

async def seed_port_congestion(session):
    count = 0

    for port in PORTS:

        session.add(
            PortCongestion(
                id=uuid.uuid4(),
                port_code=port["port_code"],
                port_name=port["port_name"],
                congestion_index=port["congestion_index"],
                avg_dwell_days=port["avg_dwell_days"],
                vessels_waiting=port["vessels_waiting"],
                advisory_text=port["advisory_text"],
                severity=port["severity"],
                measured_at=NOW,
                source="Mock Port Authority Data",
            )
        )

        count += 1

    await session.flush()

    print(f"✓ Seeded {count} port congestion records")


# ============================================================
# SEED CARRIER ADVISORIES
# ============================================================

async def seed_carrier_advisories(session):
    count = 0

    for advisory in ADVISORIES:

        session.add(
            CarrierAdvisory(
                id=uuid.uuid4(),
                carrier=advisory["carrier"],
                advisory_type=advisory["advisory_type"],
                title=advisory["title"],
                raw_text=advisory["raw_text"],
                summary=advisory["summary"],
                impact_severity=advisory["impact_severity"],
                affected_lanes=advisory["affected_lanes"],
                effective_date=advisory["effective_date"],
                source_url=advisory["source_url"],
                published_at=advisory["published_at"],
                created_at=NOW,
            )
        )

        count += 1

    await session.flush()

    print(f"✓ Seeded {count} carrier advisories")


# ============================================================
# SEED RATE ALERTS
# ============================================================

async def seed_rate_alerts(session, users):
    count = 0

    demo_user = next(
        user
        for user in users
        if user.email == "demo@freightpulse.test"
    )

    alerts = [
        {
            "trade_lane": "Egypt-China",
            "alert_type": "rate_spike",
            "message": (
                "Egypt-China freight rates increased significantly "
                "above the recent 30-day average."
            ),
            "magnitude_pct": 11.8,
            "direction": "up",
            "z_score": 2.9,
            "latest_rate": 2740.50,
            "mean_30d": 2450.30,
            "pattern_type": "one_day",
            "duration_days": 1,
            "cumulative_magnitude_pct": 11.8,
        },
        {
            "trade_lane": "UAE-Asia",
            "alert_type": "rate_drop",
            "message": (
                "UAE-Asia freight rates dropped below the recent "
                "30-day average."
            ),
            "magnitude_pct": 8.4,
            "direction": "down",
            "z_score": -2.7,
            "latest_rate": 2040.20,
            "mean_30d": 2227.40,
            "pattern_type": "sustained",
            "duration_days": 3,
            "cumulative_magnitude_pct": -8.4,
        },
        {
            "trade_lane": "UAE-Europe",
            "alert_type": "rate_spike",
            "message": (
                "UAE-Europe rates have moved above the configured "
                "alert threshold."
            ),
            "magnitude_pct": 9.6,
            "direction": "up",
            "z_score": 2.6,
            "latest_rate": 2580.00,
            "mean_30d": 2354.50,
            "pattern_type": "sustained",
            "duration_days": 2,
            "cumulative_magnitude_pct": 9.6,
        },
    ]

    for alert_data in alerts:

        session.add(
            RateAlert(
                id=uuid.uuid4(),
                user_id=demo_user.id,
                trade_lane=alert_data["trade_lane"],
                alert_type=alert_data["alert_type"],
                message=alert_data["message"],
                magnitude_pct=alert_data["magnitude_pct"],
                is_read=False,
                direction=alert_data["direction"],
                z_score=alert_data["z_score"],
                latest_rate=alert_data["latest_rate"],
                mean_30d=alert_data["mean_30d"],
                pattern_type=alert_data["pattern_type"],
                duration_days=alert_data["duration_days"],
                cumulative_magnitude_pct=alert_data[
                    "cumulative_magnitude_pct"
                ],
                last_event_date=TODAY,
                updated_at=NOW,
                created_at=NOW - timedelta(hours=random.randint(1, 48)),
            )
        )

        count += 1

    await session.flush()

    print(f"✓ Seeded {count} rate alerts")


# ============================================================
# SEED RATE ALERT RULES
# ============================================================

async def seed_rate_alert_rules(session, users):
    count = 0

    demo_user = next(
        user
        for user in users
        if user.email == "demo@freightpulse.test"
    )

    rules = [
        {
            "trade_lane": "Egypt-China",
            "alert_type": "rate_spike",
            "magnitude_pct": 8.0,
            "target_usd": None,
        },
        {
            "trade_lane": "Egypt-Europe",
            "alert_type": "rate_drop",
            "magnitude_pct": 7.0,
            "target_usd": None,
        },
        {
            "trade_lane": "UAE-Asia",
            "alert_type": "rate_spike",
            "magnitude_pct": 10.0,
            "target_usd": 2400.0,
        },
    ]

    for rule in rules:

        session.add(
            RateAlertRule(
                id=uuid.uuid4(),
                user_id=demo_user.id,
                trade_lane=rule["trade_lane"],
                alert_type=rule["alert_type"],
                magnitude_pct=rule["magnitude_pct"],
                target_usd=rule["target_usd"],
                is_active=True,
                updated_at=NOW,
                created_at=NOW,
            )
        )

        count += 1

    await session.flush()

    print(f"✓ Seeded {count} rate alert rules")


# ============================================================
# SEED ROUTE BRIEFS
# ============================================================

async def seed_route_briefs(session, users):
    count = 0

    demo_user = next(
        user
        for user in users
        if user.email == "demo@freightpulse.test"
    )

    briefs = [
        {
            "origin": "Port Said",
            "destination": "Rotterdam",
            "carrier": "Maersk",
            "cargo_type": "40ft",
            "brief_markdown": (
                "# Port Said → Rotterdam\n\n"
                "Current routing shows elevated operational risk "
                "due to Red Sea routing changes and vessel schedule "
                "adjustments.\n\n"
                "Alternative routing should be considered when "
                "schedule reliability is more important than transit cost."
            ),
            "recommendation": (
                "Review alternative routing and book capacity early."
            ),
            "risk_level": "high",
            "status": "completed",
        },
        {
            "origin": "Jebel Ali",
            "destination": "Shanghai",
            "carrier": "MSC",
            "cargo_type": "40ft",
            "brief_markdown": (
                "# Jebel Ali → Shanghai\n\n"
                "Port congestion at Jebel Ali is currently elevated. "
                "Transit reliability may be affected by vessel waiting "
                "times and extended dwell periods."
            ),
            "recommendation": (
                "Allow additional buffer time and monitor port congestion."
            ),
            "risk_level": "medium",
            "status": "completed",
        },
        {
            "origin": "Port Said",
            "destination": "Shanghai",
            "carrier": "CMA CGM",
            "cargo_type": "20ft",
            "brief_markdown": (
                "# Port Said → Shanghai\n\n"
                "Rates are currently trending upward while port "
                "conditions remain manageable."
            ),
            "recommendation": (
                "Consider securing capacity before further rate increases."
            ),
            "risk_level": "medium",
            "status": "completed",
        },
    ]

    for brief in briefs:

        session.add(
            RouteBrief(
                id=uuid.uuid4(),
                user_id=demo_user.id,
                origin=brief["origin"],
                destination=brief["destination"],
                carrier=brief["carrier"],
                cargo_type=brief["cargo_type"],
                brief_markdown=brief["brief_markdown"],
                recommendation=brief["recommendation"],
                risk_level=brief["risk_level"],
                pdf_path=None,
                status=brief["status"],
                error_message=None,
                created_at=NOW - timedelta(days=random.randint(0, 5)),
                updated_at=NOW,
            )
        )

        count += 1

    await session.flush()

    print(f"✓ Seeded {count} route briefs")


# ============================================================
# MAIN
# ============================================================

async def main():
    print()
    print("=" * 60)
    print("FreightPulse - MOCK DATA SEED")
    print("=" * 60)
    print()

    async with AsyncSessionLocal() as session:

        try:
            # ------------------------------------------------
            # Users
            # ------------------------------------------------
            users = await seed_users(session)

            # ------------------------------------------------
            # Freight rates
            # ------------------------------------------------
            await seed_freight_rates(session)

            # ------------------------------------------------
            # Rate trends
            # ------------------------------------------------
            await seed_rate_trends(session)

            # ------------------------------------------------
            # Port congestion
            # ------------------------------------------------
            await seed_port_congestion(session)

            # ------------------------------------------------
            # Carrier advisories
            # ------------------------------------------------
            await seed_carrier_advisories(session)

            # ------------------------------------------------
            # Rate alerts
            # ------------------------------------------------
            await seed_rate_alerts(session, users)

            # ------------------------------------------------
            # Rate alert rules
            # ------------------------------------------------
            await seed_rate_alert_rules(session, users)

            # ------------------------------------------------
            # Route briefs
            # ------------------------------------------------
            await seed_route_briefs(session, users)

            # ------------------------------------------------
            # Commit everything
            # ------------------------------------------------
            await session.commit()

            print()
            print("=" * 60)
            print("✓ MOCK DATA SEEDING COMPLETED SUCCESSFULLY")
            print("=" * 60)
            print()

        except Exception as exc:
            await session.rollback()

            print()
            print("=" * 60)
            print("✗ MOCK DATA SEEDING FAILED")
            print("=" * 60)
            print()
            print(f"Error: {exc}")

            raise


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())