from datetime import datetime, timezone

from app.database import AsyncSessionLocal
from app.models import PortCongestion

# MOCK DATA - Official sources such as portauthority.gov.eg and
# the DP World newsroom either do not provide structured congestion
# data or do not have publicly available data suitable for scraping.

SAMPLE_CONGESTION = [
    {
        "port_code": "EGPSD", "port_name": "Port Said",
        "congestion_index": 62.0, "avg_dwell_days": 3.2, "vessels_waiting": 14,
        "advisory_text": "Moderate congestion due to increased Suez Canal transit traffic.",
        "severity": "elevated", "source": "Manual estimate (MTS.gov.eg unavailable for live data)",
    },
    {
        "port_code": "AEJEA", "port_name": "Jebel Ali",
        "congestion_index": 78.0, "avg_dwell_days": 4.5, "vessels_waiting": 23,
        "advisory_text": "High congestion, extended dwell times reported by DP World.",
        "severity": "critical", "source": "Manual estimate (DP World newsroom unavailable for live data)",
    },
]


async def seed_port_congestion_realistic():
    async with AsyncSessionLocal() as session:
        for port in SAMPLE_CONGESTION:
            session.add(PortCongestion(**port, measured_at=datetime.now(timezone.utc)))
        await session.commit()
    print(f"Seeded {len(SAMPLE_CONGESTION)} realistic port congestion entries (mock data)")


if __name__ == "__main__":
    import asyncio
    asyncio.run(seed_port_congestion_realistic())