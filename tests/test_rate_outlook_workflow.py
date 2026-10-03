"""Registered task uses outlook artifact identity, not the legacy trend-only worker."""
from unittest.mock import MagicMock
from app.tasks import rate_outlook_generation as tasks

def test_registered_worker_passes_artifact_id(monkeypatch):
    sentinel=object()
    call=MagicMock(return_value=sentinel)
    runner=MagicMock(return_value={'status':'completed'})
    monkeypatch.setattr(tasks,'generate_rate_outlook_async',call)
    monkeypatch.setattr(tasks.asyncio,'run',runner)
    result=tasks.generate_rate_outlook.run('outlook-artifact-id')
    call.assert_called_once_with('outlook-artifact-id')
    runner.assert_called_once_with(sentinel)
    assert result['status']=='completed'


def test_grounded_task_name_rejects_legacy_queue_namespace():
    assert tasks.generate_rate_outlook.name == "app.tasks.rate_outlook_generation.generate_grounded_rate_outlook"
    assert "app.tasks.rate_outlook_generation.generate_rate_outlook" not in tasks.celery_app.tasks
