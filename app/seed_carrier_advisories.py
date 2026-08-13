from datetime import date, datetime, timedelta
from app.database import AsyncSessionLocal
from app.models import CarrierAdvisory

# MOCK DATA - Temporary until a reliable solution for real scraping is available. 
# CMA CGM, Maersk, and MSC are protected by bot protection systems 
# # such as DataDome or similar solutions. 
# Realistic sample data based on patterns observed in actual # CMA CGM RSS feed entries.
SAMPLE_ADVISORIES = [
    {
        "carrier": "CMA CGM",
        "advisory_type": "surcharge",
        "title": "ADVISORY #13 - Middle East: Dangerous Goods Surcharge Implementation",
        "summary": "Effective August/September 2026",
        "affected_lanes": ["Egypt-Europe", "UAE-Europe"],
        "effective_date": date(2026, 9, 1),
        "source_url": "https://www.cma-cgm.com/news/5555/advisory-13-middle-east-dangerous-goods-surcharge-implementation",
        "published_at": datetime.utcnow() - timedelta(days=3),
    },
    {
        "carrier": "CMA CGM",
        "advisory_type": "surcharge",
        "title": "FAK Rates - From Asia to the Mediterranean & North Africa",
        "summary": "Effective from August 15th to 30th, 2026",
        "affected_lanes": ["Egypt-China", "UAE-Asia"],
        "effective_date": date(2026, 8, 15),
        "source_url": "https://www.cma-cgm.com/news/5551/fak-rates-from-asia-to-the-mediterranean-amp-north-africa",
        "published_at": datetime.utcnow() - timedelta(days=4),
    },
    {
        "carrier": "Maersk",
        "advisory_type": "route_suspension",
        "title": "Temporary Suspension - Red Sea Routing via Suez",
        "summary": "Maersk suspends direct Red Sea routing, rerouting via Cape of Good Hope due to security concerns.",
        "affected_lanes": ["Egypt-Europe", "UAE-Europe"],
        "effective_date": date(2026, 8, 20),
        "source_url": "https://www.maersk.com/news/articles/red-sea-routing-update",
        "published_at": datetime.utcnow() - timedelta(days=1),
    },
    {
        "carrier": "Maersk",
        "advisory_type": "schedule_change",
        "title": "East-West Network Update - Port Said Rotation Change",
        "summary": "Maersk adjusts weekly rotation for Port Said calls effective mid-August.",
        "affected_lanes": ["Egypt-Europe"],
        "effective_date": date(2026, 8, 18),
        "source_url": "https://www.maersk.com/news/articles/east-west-network-update",
        "published_at": datetime.utcnow() - timedelta(hours=18),
    },
    {
        "carrier": "MSC",
        "advisory_type": "schedule_change",
        "title": "Schedule Update - Shanghai to Jebel Ali Weekly Service",
        "summary": "MSC adjusts weekly schedule for Shanghai-bound vessels by 2 days due to port congestion.",
        "affected_lanes": ["UAE-Asia", "Egypt-China"],
        "effective_date": date(2026, 8, 25),
        "source_url": "https://www.msc.com/en/newsroom/customer-advisories/schedule-update-shanghai",
        "published_at": datetime.utcnow() - timedelta(hours=6),
    },
    {
        "carrier": "MSC",
        "advisory_type": "congestion",
        "title": "Jebel Ali Port Congestion Advisory - Extended Dwell Times",
        "summary": "MSC advises customers of extended dwell times at Jebel Ali due to elevated vessel traffic.",
        "affected_lanes": ["UAE-Asia", "UAE-Europe"],
        "effective_date": date(2026, 8, 12),
        "source_url": "https://www.msc.com/en/newsroom/customer-advisories/jebel-ali-congestion",
        "published_at": datetime.utcnow() - timedelta(hours=2),
    },
]


async def seed_carrier_advisories():
    async with AsyncSessionLocal() as session:
        for adv in SAMPLE_ADVISORIES:
            session.add(CarrierAdvisory(**adv))
        await session.commit()
    print(f"Seeded {len(SAMPLE_ADVISORIES)} realistic carrier advisories (mock data - scraping blocked)")


if __name__ == "__main__":
    import asyncio
    asyncio.run(seed_carrier_advisories())