from datetime import date, datetime, timezone
from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel
import pandas as pd
from sqlalchemy import select, func, distinct, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.freight_rate import FreightRate
from app.models.bunker_rate import BunkerRate
from app.models.exchange_rate import ExchangeRate

class ForecastSeriesProfile(BaseModel):
    series_id: str
    source: str
    trade_lane: str
    container_type: str
    
    observation_count: int
    earliest_date: Optional[date]
    latest_date: Optional[date]
    chronological_span_days: int
    expected_cadence_days: int
    distinct_dates: int
    missing_periods: int
    duplicate_logical_periods: int
    
    min_rate: Optional[float]
    max_rate: Optional[float]
    mean_rate: Optional[float]
    contains_nulls: bool
    contains_invalid_rates: bool
    
    readiness: Literal["INSUFFICIENT", "MINIMAL", "BASELINE_READY", "EXTENDED_HISTORY"]


class ForecastObservation(BaseModel):
    date: date
    target_rate: float
    features: Dict[str, Any]


class ForecastDatasetMetadata(BaseModel):
    series_id: str
    source: str
    trade_lane: str
    container_type: str
    start_date: date
    end_date: date
    observation_count: int
    readiness: str
    quality_warnings: List[str]
    feature_names: List[str]


class ForecastDataset(BaseModel):
    metadata: ForecastDatasetMetadata
    observations: List[ForecastObservation]


class ForecastDatasetBuilder:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def profile_all_series(self) -> List[ForecastSeriesProfile]:
        query = select(
            FreightRate.source,
            FreightRate.trade_lane,
            FreightRate.container_type,
            func.count(FreightRate.id).label("obs_count"),
            func.min(FreightRate.rate_date).label("min_date"),
            func.max(FreightRate.rate_date).label("max_date"),
            func.count(distinct(FreightRate.rate_date)).label("distinct_dates"),
            func.min(FreightRate.rate_usd).label("min_rate"),
            func.max(FreightRate.rate_usd).label("max_rate"),
            func.avg(FreightRate.rate_usd).label("mean_rate")
        ).group_by(
            FreightRate.source, FreightRate.trade_lane, FreightRate.container_type
        )
        
        result = await self.session.execute(query)
        profiles = []
        for row in result.all():
            profiles.append(self._build_profile_from_row(row))
        return profiles

    async def profile_series(self, source: str, trade_lane: str, container_type: str) -> Optional[ForecastSeriesProfile]:
        query = select(
            FreightRate.source,
            FreightRate.trade_lane,
            FreightRate.container_type,
            func.count(FreightRate.id).label("obs_count"),
            func.min(FreightRate.rate_date).label("min_date"),
            func.max(FreightRate.rate_date).label("max_date"),
            func.count(distinct(FreightRate.rate_date)).label("distinct_dates"),
            func.min(FreightRate.rate_usd).label("min_rate"),
            func.max(FreightRate.rate_usd).label("max_rate"),
            func.avg(FreightRate.rate_usd).label("mean_rate")
        ).where(
            and_(
                FreightRate.source == source,
                FreightRate.trade_lane == trade_lane,
                FreightRate.container_type == container_type
            )
        ).group_by(
            FreightRate.source, FreightRate.trade_lane, FreightRate.container_type
        )
        
        row = (await self.session.execute(query)).first()
        if not row or row.obs_count == 0:
            return None
            
        return self._build_profile_from_row(row)

    def _build_profile_from_row(self, row) -> ForecastSeriesProfile:
        cadence_days = 7 # Freight rates are nominally weekly SCFI
        
        span_days = (row.max_date - row.min_date).days if row.max_date and row.min_date else 0
        expected_periods = (span_days // cadence_days) + 1 if span_days > 0 else 1
        
        missing = max(0, expected_periods - row.distinct_dates)
        duplicates = row.obs_count - row.distinct_dates
        
        invalid_rates = False
        if row.min_rate is not None and row.min_rate <= 0:
            invalid_rates = True
            
        readiness = "INSUFFICIENT"
        if row.distinct_dates >= 300:
            readiness = "EXTENDED_HISTORY"
        elif row.distinct_dates >= 100:
            readiness = "BASELINE_READY"
        elif row.distinct_dates >= 30:
            readiness = "MINIMAL"
            
        return ForecastSeriesProfile(
            series_id=f"{row.source}_{row.trade_lane}_{row.container_type}",
            source=row.source,
            trade_lane=row.trade_lane,
            container_type=row.container_type,
            observation_count=row.obs_count,
            earliest_date=row.min_date,
            latest_date=row.max_date,
            chronological_span_days=span_days,
            expected_cadence_days=cadence_days,
            distinct_dates=row.distinct_dates,
            missing_periods=missing,
            duplicate_logical_periods=duplicates,
            min_rate=float(row.min_rate) if row.min_rate else None,
            max_rate=float(row.max_rate) if row.max_rate else None,
            mean_rate=float(row.mean_rate) if row.mean_rate else None,
            contains_nulls=False, # DB enforces non-null
            contains_invalid_rates=invalid_rates,
            readiness=readiness
        )

    async def build_dataset(self, source: str, trade_lane: str, container_type: str) -> Optional[ForecastDataset]:
        profile = await self.profile_series(source, trade_lane, container_type)
        if not profile:
            return None
            
        warnings = []
        if profile.readiness == "INSUFFICIENT":
            warnings.append("Dataset has insufficient history for stable forecasting.")
        if profile.contains_invalid_rates:
            warnings.append("Dataset contains non-positive target rates.")
            
        # 1. Fetch Target Series
        query = select(FreightRate.rate_date, FreightRate.rate_usd).where(
            and_(
                FreightRate.source == source,
                FreightRate.trade_lane == trade_lane,
                FreightRate.container_type == container_type
            )
        ).order_by(FreightRate.rate_date.asc())
        
        result = await self.session.execute(query)
        rows = result.all()
        
        df = pd.DataFrame([{"date": r.rate_date, "target": float(r.rate_usd)} for r in rows])
        # Deduplicate to strictly preserve chronological unique dates
        df = df.drop_duplicates(subset=["date"], keep="last")
        df = df.sort_values("date").reset_index(drop=True)
        
        # 2. Extract Calendar Features (safe)
        df["date_dt"] = pd.to_datetime(df["date"])
        df["year"] = df["date_dt"].dt.year
        df["month"] = df["date_dt"].dt.month
        df["week_of_year"] = df["date_dt"].dt.isocalendar().week.astype(int)
        
        # 3. Target Lags (safe leakage rules: shift by N strictly)
        df["lag_1"] = df["target"].shift(1)
        df["lag_2"] = df["target"].shift(2)
        df["lag_4"] = df["target"].shift(4)
        
        # 4. Rolling Features (safe leakage rules: shift first, then rolling window)
        # rolling_mean_4(t) uses observations [t-4, t-3, t-2, t-1]
        df["rolling_mean_4"] = df["target"].shift(1).rolling(window=4, min_periods=1).mean()
        df["rolling_std_4"] = df["target"].shift(1).rolling(window=4, min_periods=2).std()
        
        # 5. Exogenous Features (Bunker & FX)
        # Must strictly join as_of to prevent leakage
        bunker_q = select(BunkerRate.observed_date, BunkerRate.price_usd).where(BunkerRate.port_name == "Global Average Bunker Price").order_by(BunkerRate.observed_date.asc())
        fx_q = select(ExchangeRate.observed_date, ExchangeRate.exchange_rate).where(and_(ExchangeRate.base_currency == "USD", ExchangeRate.quote_currency == "EGP")).order_by(ExchangeRate.observed_date.asc())
        
        bunker_res = await self.session.execute(bunker_q)
        fx_res = await self.session.execute(fx_q)
        
        bunker_df = pd.DataFrame([{"date_dt": pd.to_datetime(r.observed_date), "bunker_usd": float(r.price_usd)} for r in bunker_res.all()])
        fx_df = pd.DataFrame([{"date_dt": pd.to_datetime(r.observed_date), "fx_usd_egp": float(r.exchange_rate)} for r in fx_res.all()])
        
        if not bunker_df.empty:
            bunker_df = bunker_df.drop_duplicates(subset=["date_dt"], keep="last").sort_values("date_dt")
            df = pd.merge_asof(df, bunker_df, on="date_dt", direction="backward")
        else:
            df["bunker_usd"] = None
            
        if not fx_df.empty:
            fx_df = fx_df.drop_duplicates(subset=["date_dt"], keep="last").sort_values("date_dt")
            df = pd.merge_asof(df, fx_df, on="date_dt", direction="backward")
        else:
            df["fx_usd_egp"] = None
            
        # Ensure NaNs are None for JSON serialization
        df = df.where(pd.notnull(df), None)
        
        features_list = ["year", "month", "week_of_year", "lag_1", "lag_2", "lag_4", "rolling_mean_4", "rolling_std_4", "bunker_usd", "fx_usd_egp"]
        
        observations = []
        for _, row in df.iterrows():
            feats = {}
            for f in features_list:
                val = row[f]
                feats[f] = None if pd.isna(val) else val
                
            obs = ForecastObservation(
                date=row["date"],
                target_rate=row["target"],
                features=feats
            )
            observations.append(obs)
            
        metadata = ForecastDatasetMetadata(
            series_id=profile.series_id,
            source=profile.source,
            trade_lane=profile.trade_lane,
            container_type=profile.container_type,
            start_date=df["date"].min(),
            end_date=df["date"].max(),
            observation_count=len(observations),
            readiness=profile.readiness,
            quality_warnings=warnings,
            feature_names=features_list
        )
        
        return ForecastDataset(metadata=metadata, observations=observations)
