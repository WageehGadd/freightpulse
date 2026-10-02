from datetime import datetime, timezone, timedelta, date
from typing import Optional, Literal, List
from pydantic import BaseModel, Field
from sqlalchemy import select, func, distinct
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.freight_rate import FreightRate
from app.models.bunker_rate import BunkerRate
from app.models.exchange_rate import ExchangeRate
from app.models.carrier_advisory import CarrierAdvisory
from app.models.port_congestion import PortCongestion


class DataQualityReport(BaseModel):
    signal_name: str
    source_type: Literal["live", "periodic", "seeded", "static", "unknown"]
    evaluated_at: datetime
    
    available: bool
    record_count: int
    
    latest_observation_at: Optional[datetime] = None
    earliest_observation_at: Optional[datetime] = None
    age_seconds: Optional[float] = None
    
    expected_cadence_seconds: Optional[int] = None
    
    freshness_status: Literal["fresh", "aging", "stale", "unknown", "not_applicable"]
    freshness_ratio: Optional[float] = None
    
    completeness_status: Literal["complete", "gaps", "unknown", "not_applicable"]
    missing_periods: Optional[int] = None
    duplicate_count: Optional[int] = None
    
    usable_for_forecasting: bool
    usable_for_decisioning: bool
    
    warnings: List[str] = Field(default_factory=list)


class DataQualityService:
    FREIGHT_RATE_CADENCE_SECONDS = 7 * 24 * 3600

    @classmethod
    def evaluate_freight_rate_freshness(
        cls, latest_observation_date: date, evaluated_at: datetime | None = None
    ) -> tuple[str, float]:
        """Authoritative T02 freight freshness: UTC age / configured weekly cadence."""
        now = evaluated_at if evaluated_at is not None else datetime.now(timezone.utc)
        latest = cls._datetime_from_date(latest_observation_date)
        return cls._evaluate_freshness(
            (now - latest).total_seconds(), cls.FREIGHT_RATE_CADENCE_SECONDS
        )
    
    @staticmethod
    def _evaluate_freshness(age_seconds: float, expected_cadence_seconds: int) -> tuple[Literal["fresh", "aging", "stale"], float]:
        if expected_cadence_seconds <= 0:
            return "unknown", 0.0
            
        ratio = age_seconds / expected_cadence_seconds
        
        if ratio <= 1.5:
            return "fresh", ratio
        elif ratio <= 3.0:
            return "aging", ratio
        else:
            return "stale", ratio

    @staticmethod
    def _datetime_from_date(d: date | datetime | None) -> datetime | None:
        if d is None:
            return None
        if isinstance(d, datetime):
            return d
        return datetime.combine(d, datetime.min.time()).replace(tzinfo=timezone.utc)

    async def evaluate_freight_rates(self, session: AsyncSession) -> DataQualityReport:
        now = datetime.now(timezone.utc)
        
        # Configured T02 freight cadence; not inferred from stored observations.
        cadence_seconds = self.FREIGHT_RATE_CADENCE_SECONDS
        
        result = await session.execute(
            select(
                func.count().label("cnt"),
                func.min(FreightRate.rate_date).label("earliest"),
                func.max(FreightRate.rate_date).label("latest")
            )
        )
        row = result.first()
        cnt = row.cnt if row else 0
        
        if cnt == 0:
            return self._empty_report("freight_rates", "periodic", now)
            
        earliest = self._datetime_from_date(row.earliest)
        latest = self._datetime_from_date(row.latest)
        age = (now - latest).total_seconds()
        
        freshness, ratio = self.evaluate_freight_rate_freshness(row.latest, now)
        
        expected_periods = max(1, int((latest - earliest).total_seconds() / cadence_seconds) + 1)
        
        # Count distinct dates to find gaps globally (simplified approach)
        distinct_dates_res = await session.execute(select(func.count(distinct(FreightRate.rate_date))))
        distinct_dates = distinct_dates_res.scalar() or 0
        
        missing = max(0, expected_periods - distinct_dates)
        completeness = "complete" if missing == 0 else "gaps"
        
        usable_decision = freshness in ("fresh", "aging")
        # Need multiple periods for forecasting (e.g. > 4 weeks)
        usable_forecast = distinct_dates > 4
        
        warnings = []
        if missing > 0:
            warnings.append(f"Missing {missing} expected periods")
        if freshness == "stale":
            warnings.append("Data is stale")

        return DataQualityReport(
            signal_name="freight_rates",
            source_type="periodic",
            evaluated_at=now,
            available=True,
            record_count=cnt,
            latest_observation_at=latest,
            earliest_observation_at=earliest,
            age_seconds=age,
            expected_cadence_seconds=cadence_seconds,
            freshness_status=freshness,
            freshness_ratio=ratio,
            completeness_status=completeness,
            missing_periods=missing,
            duplicate_count=0, # Upsert prevents true duplicates
            usable_for_forecasting=usable_forecast,
            usable_for_decisioning=usable_decision,
            warnings=warnings
        )

    async def evaluate_bunker_rates(self, session: AsyncSession) -> DataQualityReport:
        now = datetime.now(timezone.utc)
        cadence_seconds = 24 * 3600 # Daily
        
        result = await session.execute(
            select(
                func.count().label("cnt"),
                func.min(BunkerRate.observed_date).label("earliest"),
                func.max(BunkerRate.observed_date).label("latest")
            )
        )
        row = result.first()
        cnt = row.cnt if row else 0
        
        if cnt == 0:
            return self._empty_report("bunker_rates", "periodic", now)
            
        earliest = self._datetime_from_date(row.earliest)
        latest = self._datetime_from_date(row.latest)
        age = (now - latest).total_seconds()
        
        freshness, ratio = self._evaluate_freshness(age, cadence_seconds)
        
        expected_periods = max(1, int((latest - earliest).total_seconds() / cadence_seconds) + 1)
        distinct_dates = (await session.execute(select(func.count(distinct(BunkerRate.observed_date))))).scalar() or 0
        
        missing = max(0, expected_periods - distinct_dates)
        
        usable_decision = freshness in ("fresh", "aging")
        usable_forecast = distinct_dates >= 7 # At least a week
        
        warnings = []
        if missing > 0: warnings.append(f"Missing {missing} expected periods")
        if freshness == "stale": warnings.append("Data is stale")
            
        return DataQualityReport(
            signal_name="bunker_rates",
            source_type="periodic",
            evaluated_at=now,
            available=True,
            record_count=cnt,
            latest_observation_at=latest,
            earliest_observation_at=earliest,
            age_seconds=age,
            expected_cadence_seconds=cadence_seconds,
            freshness_status=freshness,
            freshness_ratio=ratio,
            completeness_status="complete" if missing == 0 else "gaps",
            missing_periods=missing,
            duplicate_count=0,
            usable_for_forecasting=usable_forecast,
            usable_for_decisioning=usable_decision,
            warnings=warnings
        )

    async def evaluate_exchange_rates(self, session: AsyncSession) -> DataQualityReport:
        now = datetime.now(timezone.utc)
        cadence_seconds = 24 * 3600
        
        result = await session.execute(
            select(
                func.count().label("cnt"),
                func.min(ExchangeRate.observed_date).label("earliest"),
                func.max(ExchangeRate.observed_date).label("latest")
            )
        )
        row = result.first()
        cnt = row.cnt if row else 0
        
        if cnt == 0:
            return self._empty_report("exchange_rates", "periodic", now)
            
        earliest = self._datetime_from_date(row.earliest)
        latest = self._datetime_from_date(row.latest)
        age = (now - latest).total_seconds()
        
        freshness, ratio = self._evaluate_freshness(age, cadence_seconds)
        
        expected_periods = max(1, int((latest - earliest).total_seconds() / cadence_seconds) + 1)
        distinct_dates = (await session.execute(select(func.count(distinct(ExchangeRate.observed_date))))).scalar() or 0
        
        missing = max(0, expected_periods - distinct_dates)
        
        usable_decision = freshness in ("fresh", "aging")
        usable_forecast = distinct_dates >= 7
        
        warnings = []
        if missing > 0: warnings.append(f"Missing {missing} expected periods")
        if freshness == "stale": warnings.append("Data is stale")
            
        return DataQualityReport(
            signal_name="exchange_rates",
            source_type="periodic",
            evaluated_at=now,
            available=True,
            record_count=cnt,
            latest_observation_at=latest,
            earliest_observation_at=earliest,
            age_seconds=age,
            expected_cadence_seconds=cadence_seconds,
            freshness_status=freshness,
            freshness_ratio=ratio,
            completeness_status="complete" if missing == 0 else "gaps",
            missing_periods=missing,
            duplicate_count=0,
            usable_for_forecasting=usable_forecast,
            usable_for_decisioning=usable_decision,
            warnings=warnings
        )

    async def evaluate_carrier_advisories(self, session: AsyncSession) -> DataQualityReport:
        now = datetime.now(timezone.utc)
        
        result = await session.execute(
            select(
                func.count().label("cnt"),
                func.max(CarrierAdvisory.published_at).label("latest")
            )
        )
        row = result.first()
        cnt = row.cnt if row else 0
        
        if cnt == 0:
            return self._empty_report("carrier_advisories", "live", now)
            
        latest = row.latest
        if latest.tzinfo is None:
            latest = latest.replace(tzinfo=timezone.utc)
            
        age = (now - latest).total_seconds() if latest else 0.0
        
        # Event driven data is assumed fresh until expired, we don't penalize age
        
        return DataQualityReport(
            signal_name="carrier_advisories",
            source_type="live",
            evaluated_at=now,
            available=True,
            record_count=cnt,
            latest_observation_at=latest,
            earliest_observation_at=None,
            age_seconds=age,
            expected_cadence_seconds=None,
            freshness_status="not_applicable",  # Not applicable to event-driven
            freshness_ratio=None,
            completeness_status="not_applicable",
            missing_periods=None,
            duplicate_count=0,
            usable_for_forecasting=False, # Text data, usually not for time-series forecasting directly
            usable_for_decisioning=True,  # Always usable if available
            warnings=[]
        )

    async def evaluate_port_congestion(self, session: AsyncSession) -> DataQualityReport:
        now = datetime.now(timezone.utc)
        
        result = await session.execute(
            select(
                func.count().label("cnt"),
                func.max(PortCongestion.measured_at).label("latest")
            )
        )
        row = result.first()
        cnt = row.cnt if row else 0
        
        # Hardcoded to seeded/static based on repo knowledge
        return DataQualityReport(
            signal_name="port_congestion",
            source_type="seeded",
            evaluated_at=now,
            available=cnt > 0,
            record_count=cnt,
            latest_observation_at=row.latest if cnt > 0 else None,
            earliest_observation_at=None,
            age_seconds=None,
            expected_cadence_seconds=None,
            freshness_status="unknown",
            freshness_ratio=None,
            completeness_status="not_applicable",
            missing_periods=None,
            duplicate_count=0,
            usable_for_forecasting=False,
            usable_for_decisioning=False, # EXPLICITLY UNTRUSTED
            warnings=["Port congestion is seeded mock data and MUST NOT be used for live decisioning."]
        )

    def _empty_report(self, signal_name: str, source_type: str, now: datetime) -> DataQualityReport:
        return DataQualityReport(
            signal_name=signal_name,
            source_type=source_type,
            evaluated_at=now,
            available=False,
            record_count=0,
            freshness_status="unknown",
            completeness_status="unknown",
            usable_for_forecasting=False,
            usable_for_decisioning=False,
            warnings=["No data available"]
        )
