"""Internal extraction and atomic append-only persistence; caller owns commit."""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from decimal import Decimal, localcontext, Context
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.models.forecast_evaluation import EvaluationRun, EvaluationObservation, EvaluationPoint
from app.models.freight_rate import FreightRate
from app.schemas.forecast_evaluation import EvaluationInput, EvaluationConfig, EvaluationResult, Observation, Point, Phase, Availability
from app.schemas.forecast_evaluation import CANDIDATES, EVALUATION_VERSION
from app.services.forecast_evaluation import (
    evaluate, assemble, fingerprint, decimal_text, configuration_document,
)


class EvaluationIntegrityError(ValueError):
    """Identity/content mismatch; never overwrite or silently repair evidence."""


@dataclass(frozen=True)
class PersistedEvaluation:
    id: UUID
    created_at: datetime
    result: EvaluationResult


def content_fingerprint(result):
    doc = result.model_dump(mode='json')
    for item, original in zip(doc['input_snapshot']['observations'], result.input_snapshot.observations):
        item['rate'] = decimal_text(original.rate)
    return fingerprint(doc)


class EvaluationPersistenceService:
    def __init__(self, session):
        self.session = session

    async def extract(self, source, trade_lane, container_type, cutoff=None):
        stmt = select(FreightRate.rate_date, FreightRate.rate_usd).where(
            FreightRate.source == source, FreightRate.trade_lane == trade_lane,
            FreightRate.container_type == container_type)
        if cutoff is not None:
            stmt = stmt.where(FreightRate.rate_date <= cutoff)
        rows = (await self.session.execute(stmt.order_by(FreightRate.rate_date.asc())
            .execution_options(autoflush=False))).all()
        return EvaluationInput(source=source, trade_lane=trade_lane, container_type=container_type,
            observations=tuple(Observation(observation_date=d, rate=v) for d, v in rows))

    async def load(self, run_id):
        try:
            return await self._load(run_id)
        except EvaluationIntegrityError:
            raise
        except (ValueError, ArithmeticError, KeyError) as exc:
            raise EvaluationIntegrityError('Malformed persisted evaluation') from exc

    async def _load(self, run_id):
        run = (await self.session.execute(select(EvaluationRun).where(EvaluationRun.id == run_id)
            .execution_options(populate_existing=True))).scalar_one_or_none()
        if run is None:
            return None
        obs = (await self.session.execute(select(EvaluationObservation).where(
            EvaluationObservation.run_id == run_id).order_by(EvaluationObservation.ordinal)
            .execution_options(populate_existing=True))).scalars().all()
        if [o.ordinal for o in obs] != list(range(run.observation_count)):
            raise EvaluationIntegrityError('Incomplete input snapshot')
        snapshot = EvaluationInput(source=run.source, trade_lane=run.trade_lane, container_type=run.container_type,
            provenance=run.provenance, observations=tuple(Observation(observation_date=o.observation_date, rate=o.rate) for o in obs))
        config = EvaluationConfig(**{k: run.configuration[k] for k in EvaluationConfig.model_fields})
        rows = (await self.session.execute(select(EvaluationPoint).where(EvaluationPoint.run_id == run_id)
            .order_by(EvaluationPoint.target_ordinal, EvaluationPoint.candidate_name)
            .execution_options(populate_existing=True))).scalars().all()
        order = {n: i for i, n in enumerate(config.candidate_names)}
        points = tuple(Point(**{k: getattr(p, k) for k in Point.model_fields}) for p in sorted(rows,
            key=lambda p: (0 if p.protocol_phase == Phase.SELECTION_WINDOW else 1, p.target_ordinal, order.get(p.candidate_name, -1))))
        supported = (config.evaluation_version == EVALUATION_VERSION and config.forecast_horizon == 1
            and all(n in CANDIDATES for n in config.candidate_names))
        if not supported:
            if points or run.selection_status != 'UNSUPPORTED' or run.outer_status != 'UNSUPPORTED':
                raise EvaluationIntegrityError('Invalid unsupported evidence population')
        elif run.selection_status == 'INVALID' or run.outer_status == 'INVALID':
            if points or run.selection_status != 'INVALID' or run.outer_status != 'INVALID':
                raise EvaluationIntegrityError('Invalid arithmetic evidence population')
        else:
            targets = range(config.initial_train_size, len(obs))
            outer_targets = range(config.initial_train_size + config.minimum_inner_evaluation_points, len(obs))
            selection = [p for p in points if p.protocol_phase == Phase.SELECTION_WINDOW]
            outer = [p for p in points if p.protocol_phase == Phase.NESTED_OUTER]
            if ([(p.target_ordinal, p.candidate_name) for p in selection] !=
                    [(t, n) for t in targets for n in config.candidate_names]
                    or [p.target_ordinal for p in outer] != list(outer_targets)
                    or run.selection_status != ('AVAILABLE' if targets else 'INSUFFICIENT_HISTORY')
                    or run.outer_status != ('AVAILABLE' if outer_targets else 'INSUFFICIENT_HISTORY')):
                raise EvaluationIntegrityError('Incomplete phase populations')
            for p in points:
                expected_inner = p.target_ordinal - config.initial_train_size if p.protocol_phase == Phase.NESTED_OUTER else None
                if (p.candidate_name not in order or p.training_observation_count != p.target_ordinal
                        or p.target_date != obs[p.target_ordinal].observation_date
                        or p.inner_evaluation_count != expected_inner):
                    raise EvaluationIntegrityError('Invalid fold structure')
        result = assemble(snapshot, config, points, Availability(run.selection_status), Availability(run.outer_status))
        if (content_fingerprint(result) != run.content_fingerprint
                or result.dataset_fingerprint != run.dataset_fingerprint
                or result.configuration_fingerprint != run.configuration_fingerprint
                or configuration_document(config) != run.configuration
                or result.final_champion != run.final_champion
                or result.winner_switch_count != run.winner_switch_count
                or result.outer_metrics.evaluation_count != run.outer_evaluation_count
                or (result.candidate_summaries[0].metrics.evaluation_count if result.candidate_summaries else 0) != run.selection_evaluation_count
                or config.initial_train_size != run.initial_train_size
                or config.minimum_inner_evaluation_points != run.minimum_inner_evaluation_points
                or config.forecast_horizon != run.forecast_horizon
                or config.evaluation_version != run.evaluation_version
                or (obs[-1].observation_date if obs else None) != run.dataset_cutoff):
            raise EvaluationIntegrityError('Persisted evaluation integrity mismatch')
        return PersistedEvaluation(run.id, run.created_at, result)

    async def persist(self, result):
        # Verify completed pure evidence, including bypassed frozen-model validation.
        try:
            if evaluate(result.input_snapshot, result.configuration) != result:
                raise EvaluationIntegrityError('Evaluation evidence is inconsistent')
            with localcontext(Context(prec=40)):
                for o in result.input_snapshot.observations:
                    if (not o.rate.is_finite() or abs(o.rate) >= Decimal('100000000')
                            or o.rate != o.rate.quantize(Decimal('0.01'))):
                        raise EvaluationIntegrityError('Snapshot must fit exact source NUMERIC(10,2)')
            digest = content_fingerprint(result)
        except EvaluationIntegrityError:
            raise
        except (ValueError, ArithmeticError) as exc:
            raise EvaluationIntegrityError('Invalid completed evaluation') from exc
        s, c = result.input_snapshot, result.configuration
        values = dict(source=s.source, trade_lane=s.trade_lane, container_type=s.container_type,
            dataset_cutoff=s.observations[-1].observation_date if s.observations else None,
            observation_count=len(s.observations), dataset_fingerprint=result.dataset_fingerprint,
            evaluation_version=c.evaluation_version, configuration_fingerprint=result.configuration_fingerprint,
            configuration=configuration_document(c), content_fingerprint=digest,
            initial_train_size=c.initial_train_size, minimum_inner_evaluation_points=c.minimum_inner_evaluation_points,
            forecast_horizon=c.forecast_horizon,
            selection_evaluation_count=result.candidate_summaries[0].metrics.evaluation_count if result.candidate_summaries else 0,
            outer_evaluation_count=result.outer_metrics.evaluation_count, final_champion=result.final_champion,
            selection_status=result.selection_status.value, outer_status=result.outer_status.value,
            winner_switch_count=result.winner_switch_count, provenance=s.provenance.value)
        # A savepoint rolls back this artifact only. No hidden outer commit/rollback.
        async with self.session.begin_nested():
            run_id = (await self.session.execute(insert(EvaluationRun).values(**values)
                .on_conflict_do_nothing(constraint='uq_evaluation_identity').returning(EvaluationRun.id))).scalar_one_or_none()
            if run_id is not None:
                self.session.add_all([EvaluationObservation(run_id=run_id, ordinal=i,
                    observation_date=o.observation_date, rate=o.rate) for i, o in enumerate(s.observations)])
                self.session.add_all([EvaluationPoint(run_id=run_id, **p.model_dump(mode='python')) for p in result.points])
                await self.session.flush()
            else:
                run_id = (await self.session.execute(select(EvaluationRun.id).where(
                    EvaluationRun.source == s.source, EvaluationRun.trade_lane == s.trade_lane,
                    EvaluationRun.container_type == s.container_type,
                    EvaluationRun.dataset_fingerprint == result.dataset_fingerprint,
                    EvaluationRun.evaluation_version == c.evaluation_version,
                    EvaluationRun.configuration_fingerprint == result.configuration_fingerprint))).scalar_one()
            existing = await self.load(run_id)
            if content_fingerprint(existing.result) != digest:
                raise EvaluationIntegrityError('Existing identity has conflicting evidence')
            return existing
