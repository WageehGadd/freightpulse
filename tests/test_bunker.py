from app.redis_client import get_redis


async def test_bunker_ifo380_empty_when_no_cache(client, auth_headers):
    redis = get_redis()
    keys = await redis.keys("bunker:ifo380:*")
    for key in keys:
        await redis.delete(key)  # delete any existing data before the test

    response = await client.get("/api/v1/bunker/ifo380", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["ifo380_prices"] == {}


async def test_bunker_ifo380_returns_cached_value(client, auth_headers):
    redis = get_redis()
    await redis.set("bunker:ifo380:rotterdam", "636.50", ex=60)

    response = await client.get("/api/v1/bunker/ifo380", headers=auth_headers)
    data = response.json()["ifo380_prices"]
    assert data.get("rotterdam") == 636.50

    await redis.delete("bunker:ifo380:rotterdam")  # delete the cached data after the test
