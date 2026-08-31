import os
import time
import requests
import concurrent.futures
import pytest

API_URL = "http://localhost:8000/api/v1"
API_KEY = "test_admin_key_123"
HEADERS = {"X-API-Key": API_KEY}


def run_route_brief(test_name: str, payload: dict) -> bool:
    start_t = time.time()
    try:
        res = requests.post(f"{API_URL}/route-briefs", json=payload, headers=HEADERS)
    except requests.exceptions.ConnectionError:
        pytest.skip("Live backend is not running at localhost:8000")

    if res.status_code == 202:
        brief_id = res.json()["id"]
        status = "pending"
        for _ in range(45):
            r_stat = requests.get(f"{API_URL}/route-briefs/{brief_id}/status", headers=HEADERS)
            if r_stat.status_code == 200:
                status = r_stat.json().get("status")
                if status in ["completed", "failed"]:
                    break
            time.sleep(1)
        lat = time.time() - start_t
        
        if status == "completed":
            r_final = requests.get(f"{API_URL}/route-briefs/{brief_id}", headers=HEADERS)
            assert r_final.status_code == 200
            final_data = r_final.json()
            assert "risk_level" in final_data
            return True
        return False
    elif res.status_code == 422 and "malformed" in test_name.lower():
        return True
    return False


@pytest.mark.ai_live
def test_admin_api_health_e2e():
    """Verify HTTP API authentication and Admin DB/Redis integration."""
    if os.getenv("FREIGHTPULSE_ENABLE_LIVE_AI") != "1" or not os.getenv("AZURE_OPENAI_API_KEY"):
        pytest.skip("Live AI tests are disabled or AZURE_OPENAI_API_KEY is not set")

    try:
        res = requests.get(f"{API_URL}/ai/health")
    except requests.exceptions.ConnectionError:
        pytest.skip("Live backend is not running at localhost:8000")

    assert res.status_code == 401

    res = requests.get(f"{API_URL}/ai/health", headers=HEADERS)
    assert res.status_code == 200
    data = res.json()
    assert data["provider"] == "azure"
    assert data["model"] == "gpt-4.1-mini"
    assert data["redis_status"] == "connected"


@pytest.mark.ai_live
def test_route_brief_e2e_standard_and_high_risk():
    """Verify True E2E HTTP pipeline (FastAPI -> DB -> Celery -> Azure -> Result)"""
    if os.getenv("FREIGHTPULSE_ENABLE_LIVE_AI") != "1" or not os.getenv("AZURE_OPENAI_API_KEY"):
        pytest.skip("Live AI tests are disabled or AZURE_OPENAI_API_KEY is not set")
    
    assert run_route_brief("Normal Route", {
        "origin": "Shanghai",
        "destination": "Los Angeles",
        "carrier": "MSC",
        "cargo_type": "Electronics"
    })
    
    assert run_route_brief("High Risk Route", {
        "origin": "Red Sea",
        "destination": "Rotterdam",
        "carrier": "Maersk",
        "cargo_type": "Hazardous"
    })
    
    assert run_route_brief("Arabic Request", {
        "origin": "دبي",
        "destination": "جدة",
        "carrier": "Hapag-Lloyd",
        "cargo_type": "General Cargo"
    })
    
    assert run_route_brief("Malformed Request", {
        "origin": "Shanghai",
        "destination": "Los Angeles"
    })


@pytest.mark.ai_live
def test_route_brief_e2e_concurrency():
    """Verify Celery Prefork properly isolates memory and concurrent async tasks do not deadlock."""
    if os.getenv("FREIGHTPULSE_ENABLE_LIVE_AI") != "1" or not os.getenv("AZURE_OPENAI_API_KEY"):
        pytest.skip("Live AI tests are disabled or AZURE_OPENAI_API_KEY is not set")

    payload = {
        "origin": "Shanghai",
        "destination": "Los Angeles",
        "carrier": "MSC",
        "cargo_type": "Electronics"
    }
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(run_route_brief, f"Concurrent {i}", payload) for i in range(5)]
        results = [f.result() for f in concurrent.futures.as_completed(futures)]
        assert all(results)
