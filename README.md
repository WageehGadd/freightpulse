# FreightPulse Backend API Reference & Documentation

FreightPulse is an AI-powered freight and logistics intelligence platform providing real-time freight rates, statistical trend analysis, port congestion tracking, carrier advisories, automated rate alerts, and AI route briefs.

---

## 🌐 Base URL & Server Info

- **Base URL**: `http://localhost:8000/api/v1`
- **Interactive Swagger Docs (OpenAPI UI)**: `http://localhost:8000/docs`
- **ReDoc UI**: `http://localhost:8000/redoc`

---

## 🔐 Authentication & Headers

### Authentication Method
Endpoints that require authentication expect the **`X-API-Key`** header:

```http
X-API-Key: <YOUR_API_KEY>
```

### API Key Types
1. **Master / Admin API Key**:
   - Configured in `.env` as `API_KEY` (default: `dev_local_api_key_123` or `fp_live_default_secret_key`).
   - Grants full access including **Admin-only** AI telemetry and budget endpoints.
2. **User API Keys**:
   - Generated per user and stored securely (SHA-256 hashed).
   - Prefix format: `fp_live_xxxxxxxx...`

### How to Generate a New API Key
Run the generator script inside the project environment:
```bash
# Direct command (virtualenv)
python -m scripts.create_api_key user@example.com "My API Key"

# Or using Docker Compose
docker compose exec backend python -m scripts.create_api_key user@example.com "My API Key"
```

### Rate Limiting
Endpoints protected by the rate limiter allow up to **100 requests per minute** per API key. If exceeded, the API returns HTTP `429 Too Many Requests`.

---

## ⚠️ Standard Error Response Envelope

All API errors return a standardized JSON envelope:

```json
{
  "error": {
    "code": "UNAUTHORIZED",
    "message": "Missing API Key",
    "details": {}
  }
}
```

Common Error Codes:
- `400` : `BAD_REQUEST` / `VALIDATION_ERROR`
- `401` : `UNAUTHORIZED` (Missing or invalid `X-API-Key`)
- `403` : `FORBIDDEN` (Admin privileges required)
- `404` : `NOT_FOUND`
- `409` : `CONFLICT`
- `429` : `RATE_LIMITED`
- `500` : `INTERNAL_ERROR`

---

## 📑 API Endpoint Summary Table

| Category | Method | Endpoint | Auth Required (`X-API-Key`) | Description |
| :--- | :--- | :--- | :--- | :--- |
| **Health** | `GET` | `/api/v1/health` | ❌ Public | System DB, Redis, and scraper health check |
| **Dashboard** | `GET` | `/api/v1/dashboard` | 🔒 **Yes** (100 req/min) | Aggregated dashboard overview metrics |
| **Rates** | `GET` | `/api/v1/rates/all` | ❌ Public | Latest rates and 7-day trend for all lanes |
| **Rates** | `GET` | `/api/v1/rates/compare` | ❌ Public | Rate comparison vs 7d, 30d, 90d averages |
| **Rates** | `GET` | `/api/v1/rates/{lane}` | ❌ Public | 30-day rate history and statistical trend |
| **Rates** | `POST` | `/api/v1/rates/outlook/{trend_id}` | ❌ Public | Trigger AI rate outlook job for a trend |
| **Ports** | `GET` | `/api/v1/ports/congestion-map` | ❌ Public | Global port congestion map coordinates & status |
| **Ports** | `GET` | `/api/v1/ports/{code}/congestion` | ❌ Public | Detailed congestion metrics for a specific port |
| **Carriers** | `GET` | `/api/v1/carriers` | ❌ Public | List ocean carriers with advisory counts and metadata |
| **Carriers** | `GET` | `/api/v1/carriers/advisories` | ❌ Public | List carrier advisories with filters |
| **Forex** | `GET` | `/api/v1/exchange-rate/usd-egp` | ❌ Public | Cached USD to EGP foreign exchange rate |
| **Bunker** | `GET` | `/api/v1/bunker/ifo380` | ❌ Public | Cached IFO380 bunker fuel prices by port |
| **Alerts** | `POST` | `/api/v1/alerts/rules` | 🔒 **Yes** (User) | Create custom user rate alert rule |
| **Alerts** | `GET` | `/api/v1/alerts/rules` | 🔒 **Yes** (User) | List user active alert rules |
| **Alerts** | `DELETE`| `/api/v1/alerts/rules/{rule_id}` | 🔒 **Yes** (User) | Delete user alert rule |
| **Alerts** | `GET` | `/api/v1/alerts/events` | 🔒 **Yes** (User) | List triggered alert events for current user |
| **Alerts** | `GET` | `/api/v1/alerts` | ❌ Public | List triggered alerts (shared MVP) |
| **Alerts** | `PATCH`| `/api/v1/alerts/{alert_id}/read` | ❌ Public | Mark an alert event as read |
| **Route Briefs**| `POST` | `/api/v1/route-briefs` | 🔒 **Yes** (User) | Generate new AI route brief |
| **Route Briefs**| `GET` | `/api/v1/route-briefs/{id}/status` | 🔒 **Yes** (User/Admin) | Check route brief generation status |
| **Route Briefs**| `GET` | `/api/v1/route-briefs/{id}/pdf` | 🔒 **Yes** (User/Admin) | Download generated route brief PDF |
| **AI** | `GET` | `/api/v1/ai/health` | 🔒 **Yes** (User) | Check AI model configuration and prompt versions |
| **AI** | `GET` | `/api/v1/ai/metrics` | 🛡️ **Yes (Admin Only)**| AI spend, daily budget, and telemetry |
| **AI** | `GET` | `/api/v1/ai/prompts` | 🛡️ **Yes (Admin Only)**| List registered prompt versions |
| **AI** | `POST` | `/api/v1/ai/trends/compute` | ❌ Public / Internal | Trigger daily trend computation task |
| **AI** | `POST` | `/api/v1/ai/anomalies/detect` | ❌ Public / Internal | Trigger anomaly detection task |
| **AI** | `GET` | `/api/v1/ai/trends/{trade_lane}` | ❌ Public | Latest trend and AI outlook for a trade lane |
| **AI** | `GET` | `/api/v1/ai/alerts` | ❌ Public | Retrieve anomaly alerts |
| **AI** | `PUT` | `/api/v1/ai/alerts/{alert_id}/read`| ❌ Public | Mark an AI alert as read |
| **Users** | `GET` | `/api/v1/users` | 🔒 **Yes** (User) | Retrieve list of registered users |
| **Users** | `GET` | `/api/v1/users/me` | 🔒 **Yes** (User) | Retrieve current authenticated user profile |
| **Users** | `GET` | `/api/v1/users/{user_id}` | 🔒 **Yes** (User) | Retrieve single user by ID |
| **WebSocket** | `WS` | `/api/v1/ws/alerts/{user_id}` | 🔒 **Yes** (Handshake) | Real-time Redis alert push stream |

---

## 📖 Detailed Endpoint Reference

---

### 1. Health

#### `GET /api/v1/health`
- **Auth**: None (Public)
- **Description**: Returns database connectivity, Redis cache connectivity, and latest timestamps for data scrapers.
- **cURL Example**:
  ```bash
  curl -X GET http://localhost:8000/api/v1/health
  ```
- **Response `200 OK`**:
  ```json
  {
    "status": "healthy",
    "database": "connected",
    "redis": "connected",
    "last_scrape": {
      "scfi": "2026-08-11T03:57:04.673226+00:00",
      "fbx": null,
      "port_advisories": "2026-08-11T03:57:04.819300+00:00",
      "carrier_advisories": "2026-08-11T03:57:04.836990+00:00"
    }
  }
  ```

---

### 2. Dashboard

#### `GET /api/v1/dashboard`
- **Auth**: 🔒 **Required** (`X-API-Key`)
- **Rate Limit**: 100 requests / minute
- **Description**: Aggregates top-level KPI metrics for the web dashboard: active trade lanes, 30-day rate trend curve, port congestion overview, latest 5 carrier advisories, and unread alert count.
- **cURL Example**:
  ```bash
  curl -X GET http://localhost:8000/api/v1/dashboard \
    -H "X-API-Key: dev_local_api_key_123"
  ```
- **Response `200 OK`**:
  ```json
  {
    "tracked_lanes_count": 8,
    "lanes_summary": [
      {
        "trade_lane": "CNSHA-EGPSD",
        "current_rate": 2450.00,
        "trend": "rising",
        "change_7d_pct": 4.5
      }
    ],
    "rate_trend_30d": [
      {
        "date": "2026-08-01",
        "avg_rate_usd": 2340.50
      }
    ],
    "port_congestion_overview": [
      {
        "port_code": "EGPSD",
        "port_name": "Port Said",
        "severity": "elevated",
        "congestion_index": 62.5
      }
    ],
    "recent_advisories": [
      {
        "carrier": "MSC",
        "title": "Peak Season Surcharge Asia to Med",
        "advisory_type": "surcharge",
        "published_at": "2026-08-11T03:57:04.836990+00:00"
      }
    ],
    "unread_alert_count": 3
  }
  ```

---

### 3. Freight Rates

#### `GET /api/v1/rates/all`
- **Auth**: None (Public)
- **Description**: Returns the latest freight rate for all trade lanes and container sizes (`20ft` / `40ft`), including data freshness and 7-day change percentage.
- **cURL Example**:
  ```bash
  curl -X GET http://localhost:8000/api/v1/rates/all
  ```
- **Response `200 OK`**:
  ```json
  {
    "lanes": [
      {
        "trade_lane": "CNSHA-EGPSD",
        "container_type": "40ft",
        "current_rate_usd": 2450.0,
        "source": "SCFI",
        "rate_date": "2026-08-10",
        "change_7d_pct": 3.2,
        "trend": "rising",
        "data_freshness": "2026-08-11T03:57:04.673226+00:00"
      }
    ]
  }
  ```

#### `GET /api/v1/rates/compare`
- **Auth**: None (Public)
- **Query Parameters**:
  - `trade_lane` (*string, required*): Trade lane code (e.g. `CNSHA-EGPSD`)
  - `container_type` (*string, optional, default: `"40ft"`*): `"20ft"` or `"40ft"`
- **cURL Example**:
  ```bash
  curl -X GET "http://localhost:8000/api/v1/rates/compare?trade_lane=CNSHA-EGPSD&container_type=40ft"
  ```
- **Response `200 OK`**:
  ```json
  {
    "trade_lane": "CNSHA-EGPSD",
    "container_type": "40ft",
    "current_rate": 2450.0,
    "avg_7d": 2400.0,
    "avg_30d": 2320.0,
    "avg_90d": 2150.0,
    "vs_7d_pct": 2.08,
    "vs_30d_pct": 5.60,
    "vs_90d_pct": 13.95
  }
  ```

#### `GET /api/v1/rates/{lane}`
- **Auth**: None (Public)
- **Path Parameters**:
  - `lane` (*string, required*): e.g. `CNSHA-EGPSD`
- **Query Parameters**:
  - `container_type` (*string, optional, default: `"40ft"`*): `"20ft"` or `"40ft"`
- **cURL Example**:
  ```bash
  curl -X GET "http://localhost:8000/api/v1/rates/CNSHA-EGPSD?container_type=40ft"
  ```
- **Response `200 OK`**:
  ```json
  {
    "trade_lane": "CNSHA-EGPSD",
    "container_type": "40ft",
    "current_rate": 2450.0,
    "history": [
      { "date": "2026-07-20", "rate_usd": 2200.0 },
      { "date": "2026-08-10", "rate_usd": 2450.0 }
    ],
    "trend": {
      "direction": "rising",
      "slope_per_week": 45.2,
      "change_7d_pct": 3.2,
      "change_30d_pct": 11.36,
      "anomaly_flag": false
    }
  }
  ```

#### `POST /api/v1/rates/outlook/{trend_id}`
- **Auth**: None (Public)
- **Path Parameters**:
  - `trend_id` (*UUID, required*): The UUID of the `RateTrend` record.
- **Description**: Asynchronously enqueues an LLM task to produce an AI rate outlook and market recommendation.
- **cURL Example**:
  ```bash
  curl -X POST http://localhost:8000/api/v1/rates/outlook/3fa85f64-5717-4562-b3fc-2c963f66afa6
  ```
- **Response `200 OK`**:
  ```json
  {
    "trend_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "status": "pending"
  }
  ```

---

### 4. Ports & Congestion

#### `GET /api/v1/ports/congestion-map`
- **Auth**: None (Public)
- **Description**: Returns all tracked global ports with geographic coordinates, latest congestion index, vessels waiting, and congestion severity for interactive map rendering.
- **cURL Example**:
  ```bash
  curl -X GET http://localhost:8000/api/v1/ports/congestion-map
  ```
- **Response `200 OK`**:
  ```json
  {
    "ports": [
      {
        "port_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "port_code": "EGPSD",
        "port_name": "Port Said",
        "country": "Egypt",
        "latitude": 31.2653,
        "longitude": 32.3019,
        "congestion_index": 65.0,
        "vessels_waiting": 14,
        "severity": "elevated"
      }
    ]
  }
  ```

#### `GET /api/v1/ports/{code}/congestion`
- **Auth**: None (Public)
- **Path Parameters**:
  - `code` (*string, required*): Port code, case-insensitive (e.g. `EGPSD`, `AEJEA`, `CNSHA`)
- **cURL Example**:
  ```bash
  curl -X GET http://localhost:8000/api/v1/ports/EGPSD/congestion
  ```
- **Response `200 OK`**:
  ```json
  {
    "port_code": "EGPSD",
    "port_name": "Port Said",
    "congestion_index": 65.0,
    "avg_dwell_days": 4.2,
    "vessels_waiting": 14,
    "severity": "elevated",
    "advisory_text": "Berth delays up to 48h expected due to weather.",
    "measured_at": "2026-08-11T03:57:04.819300+00:00"
  }
  ```

---

### 5. Carriers & Carrier Advisories

#### `GET /api/v1/carriers`
- **Auth**: None (Public)
- **Description**: Retrieve a list of tracked ocean carriers, their standardized carrier codes, full company names, and current advisory counts.
- **cURL Example**:
  ```bash
  curl -X GET "http://localhost:8000/api/v1/carriers"
  ```
- **Response `200 OK`**:
  ```json
  {
    "carriers": [
      {
        "name": "CMA CGM",
        "code": "CMACGM",
        "full_name": "CMA CGM Group",
        "advisories_count": 2
      },
      {
        "name": "Maersk",
        "code": "MAEU",
        "full_name": "A.P. Moller – Maersk",
        "advisories_count": 2
      },
      {
        "name": "MSC",
        "code": "MSCU",
        "full_name": "Mediterranean Shipping Company",
        "advisories_count": 2
      }
    ]
  }
  ```

#### `GET /api/v1/carriers/advisories`
- **Auth**: None (Public)
- **Query Parameters**:
  - `carrier` (*string, optional*): Filter by carrier name (e.g. `MSC`, `Maersk`, `CMACGM`)
  - `type` (*string, optional*): Filter by advisory type (e.g. `surcharge`, `route_suspension`, `congestion`)
  - `affected_lane` (*string, optional*): Filter by affected lane (e.g. `CNSHA-EGPSD`)
- **cURL Example**:
  ```bash
  curl -X GET "http://localhost:8000/api/v1/carriers/advisories?carrier=MSC&type=surcharge"
  ```
- **Response `200 OK`**:
  ```json
  {
    "advisories": [
      {
        "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
        "carrier": "MSC",
        "advisory_type": "surcharge",
        "title": "Emergency Bunker Surcharge Notice",
        "summary": "Implementation of $150/TEU surcharge effective Sept 1.",
        "affected_lanes": ["CNSHA-EGPSD", "AEJEA-EGPSD"],
        "effective_date": "2026-09-01",
        "impact_severity": "medium",
        "source_url": "https://msc.com/advisories/123",
        "published_at": "2026-08-11T03:57:04.836990+00:00"
      }
    ]
  }
  ```


---

### 6. Foreign Exchange & Bunker Prices

#### `GET /api/v1/exchange-rate/usd-egp`
- **Auth**: None (Public)
- **Description**: Returns the latest cached USD to Egyptian Pound (EGP) exchange rate.
- **cURL Example**:
  ```bash
  curl -X GET http://localhost:8000/api/v1/exchange-rate/usd-egp
  ```
- **Response `200 OK`**:
  ```json
  {
    "usd_egp": 48.65
  }
  ```

#### `GET /api/v1/bunker/ifo380`
- **Auth**: None (Public)
- **Description**: Returns cached IFO380 marine fuel prices across tracked bunkering ports.
- **cURL Example**:
  ```bash
  curl -X GET http://localhost:8000/api/v1/bunker/ifo380
  ```
- **Response `200 OK`**:
  ```json
  {
    "ifo380_prices": {
      "singapore": 490.5,
      "rotterdam": 475.0,
      "suez": 510.0
    }
  }
  ```

---

### 7. Rate Alerts & Custom Rules

#### `POST /api/v1/alerts/rules`
- **Auth**: 🔒 **Required** (`X-API-Key`)
- **Description**: Creates a user-specific monitoring rule for rate spikes, drops, or absolute price thresholds.
- **Request Body**:
  ```json
  {
    "trade_lane": "CNSHA-EGPSD",
    "alert_type": "rate_spike",
    "magnitude_pct": 10.0
  }
  ```
  *(Note: For `rate_spike` or `rate_drop`, provide `magnitude_pct`. For `threshold_above` or `threshold_below`, provide `target_usd`)*.
- **cURL Example**:
  ```bash
  curl -X POST http://localhost:8000/api/v1/alerts/rules \
    -H "Content-Type: application/json" \
    -H "X-API-Key: dev_local_api_key_123" \
    -d '{
      "trade_lane": "CNSHA-EGPSD",
      "alert_type": "rate_spike",
      "magnitude_pct": 10.0
    }'
  ```
- **Response `201 Created`**:
  ```json
  {
    "id": "7b79a5c8-18e4-4d82-b7b5-0c6f1a8e1b12",
    "trade_lane": "CNSHA-EGPSD",
    "alert_type": "rate_spike",
    "magnitude_pct": 10.0,
    "target_usd": null,
    "is_active": true,
    "created_at": "2026-08-20T23:55:00Z"
  }
  ```

#### `GET /api/v1/alerts/rules`
- **Auth**: 🔒 **Required** (`X-API-Key`)
- **Description**: Returns all active rules created by the authenticated user.
- **cURL Example**:
  ```bash
  curl -X GET http://localhost:8000/api/v1/alerts/rules \
    -H "X-API-Key: dev_local_api_key_123"
  ```
- **Response `200 OK`**:
  ```json
  [
    {
      "id": "7b79a5c8-18e4-4d82-b7b5-0c6f1a8e1b12",
      "trade_lane": "CNSHA-EGPSD",
      "alert_type": "rate_spike",
      "magnitude_pct": 10.0,
      "target_usd": null,
      "is_active": true,
      "created_at": "2026-08-20T23:55:00Z"
    }
  ]
  ```

#### `DELETE /api/v1/alerts/rules/{rule_id}`
- **Auth**: 🔒 **Required** (`X-API-Key`)
- **Path Parameters**:
  - `rule_id` (*UUID, required*): ID of the rule to delete.
- **cURL Example**:
  ```bash
  curl -X DELETE http://localhost:8000/api/v1/alerts/rules/7b79a5c8-18e4-4d82-b7b5-0c6f1a8e1b12 \
    -H "X-API-Key: dev_local_api_key_123"
  ```
- **Response `204 No Content`**

#### `GET /api/v1/alerts/events`
- **Auth**: 🔒 **Required** (`X-API-Key`)
- **Description**: Retrieves triggered alert events relevant to the authenticated user.
- **cURL Example**:
  ```bash
  curl -X GET http://localhost:8000/api/v1/alerts/events \
    -H "X-API-Key: dev_local_api_key_123"
  ```

#### `GET /api/v1/alerts`
- **Auth**: None (Public / Shared MVP)
- **Query Parameters**:
  - `unread` (*boolean, optional*): `true` to filter unread alerts only.
- **cURL Example**:
  ```bash
  curl -X GET "http://localhost:8000/api/v1/alerts?unread=true"
  ```

#### `PATCH /api/v1/alerts/{alert_id}/read`
- **Auth**: None (Public)
- **Path Parameters**:
  - `alert_id` (*UUID, required*)
- **Description**: Marks an alert event as read.
- **cURL Example**:
  ```bash
  curl -X PATCH http://localhost:8000/api/v1/alerts/7b79a5c8-18e4-4d82-b7b5-0c6f1a8e1b12/read
  ```
- **Response `200 OK`**:
  ```json
  {
    "id": "7b79a5c8-18e4-4d82-b7b5-0c6f1a8e1b12",
    "is_read": true
  }
  ```

---

### 8. AI Route Briefs

#### `POST /api/v1/route-briefs`
- **Auth**: 🔒 **Required** (`X-API-Key`)
- **Description**: Submits a request for a comprehensive AI Route Brief analyzing rates, port delays, advisories, and risk factors. Generates a formatted PDF in the background.
- **Request Body**:
  ```json
  {
    "origin": "CNSHA",
    "destination": "EGPSD",
    "carrier": "MSC",
    "cargo_type": "40ft"
  }
  ```
- **cURL Example**:
  ```bash
  curl -X POST http://localhost:8000/api/v1/route-briefs \
    -H "Content-Type: application/json" \
    -H "X-API-Key: dev_local_api_key_123" \
    -d '{
      "origin": "CNSHA",
      "destination": "EGPSD",
      "carrier": "MSC",
      "cargo_type": "40ft"
    }'
  ```
- **Response `201 Created`**:
  ```json
  {
    "id": "a9d5e381-e231-419b-a3d8-55a2c20a4421",
    "user_id": "c1f75322-8321-4f3b-871d-66e2c20a9911",
    "origin": "CNSHA",
    "destination": "EGPSD",
    "carrier": "MSC",
    "cargo_type": "40ft",
    "status": "pending",
    "brief_markdown": null,
    "recommendation": null,
    "risk_level": null,
    "pdf_path": null,
    "error_message": null,
    "created_at": "2026-08-20T23:56:00Z"
  }
  ```

#### `GET /api/v1/route-briefs/{brief_id}/status`
- **Auth**: 🔒 **Required** (`X-API-Key`)
- **Path Parameters**:
  - `brief_id` (*UUID, required*)
- **Description**: Returns current generation status (`pending`, `generating`, `completed`, `failed`).
- **cURL Example**:
  ```bash
  curl -X GET http://localhost:8000/api/v1/route-briefs/a9d5e381-e231-419b-a3d8-55a2c20a4421/status \
    -H "X-API-Key: dev_local_api_key_123"
  ```
- **Response `200 OK`**:
  ```json
  {
    "id": "a9d5e381-e231-419b-a3d8-55a2c20a4421",
    "status": "completed",
    "error_message": null
  }
  ```

#### `GET /api/v1/route-briefs/{brief_id}/pdf`
- **Auth**: 🔒 **Required** (`X-API-Key`)
- **Path Parameters**:
  - `brief_id` (*UUID, required*)
- **Description**: Downloads the compiled PDF document of the completed route brief (`application/pdf`).
- **cURL Example**:
  ```bash
  curl -X GET http://localhost:8000/api/v1/route-briefs/a9d5e381-e231-419b-a3d8-55a2c20a4421/pdf \
    -H "X-API-Key: dev_local_api_key_123" \
    --output route_brief.pdf
  ```

---

### 9. AI Intelligence & Telemetry

#### `GET /api/v1/ai/health`
- **Auth**: 🔒 **Required** (`X-API-Key`)
- **Description**: Returns AI provider settings and active prompt versions.
- **cURL Example**:
  ```bash
  curl -X GET http://localhost:8000/api/v1/ai/health \
    -H "X-API-Key: dev_local_api_key_123"
  ```
- **Response `200 OK`**:
  ```json
  {
    "status": "healthy",
    "provider": "openai",
    "model": "gpt-4o-mini",
    "active_prompts": {
      "carrier_summarizer": "v1",
      "rate_outlook": "v1",
      "route_brief": "v1"
    }
  }
  ```

#### `GET /api/v1/ai/metrics`
- **Auth**: 🛡️ **Required (Admin Only)** (`X-API-Key` with `is_admin=True` or master `API_KEY`)
- **Description**: Returns daily OpenAI budget limits, reserved costs, committed spend, token consumption, and latency metrics.
- **cURL Example**:
  ```bash
  curl -X GET http://localhost:8000/api/v1/ai/metrics \
    -H "X-API-Key: dev_local_api_key_123"
  ```
- **Response `200 OK`**:
  ```json
  {
    "budget": {
      "daily_budget_usd": 10.0,
      "actual_usd": 1.24,
      "reserved_usd": 0.05,
      "committed_usd": 1.29
    },
    "telemetry": {
      "total_requests": 42,
      "average_latency_ms": 780.5
    }
  }
  ```

#### `GET /api/v1/ai/prompts`
- **Auth**: 🛡️ **Required (Admin Only)** (`X-API-Key`)
- **Description**: Lists registered prompt version metadata for all AI capabilities.
- **cURL Example**:
  ```bash
  curl -X GET http://localhost:8000/api/v1/ai/prompts \
    -H "X-API-Key: dev_local_api_key_123"
  ```

#### `POST /api/v1/ai/trends/compute`
- **Auth**: None (Public / Scheduled Trigger)
- **Description**: Dispatches the asynchronous Celery job to compute moving averages, linear regression slopes, and trends across all trade lanes.
- **cURL Example**:
  ```bash
  curl -X POST http://localhost:8000/api/v1/ai/trends/compute
  ```

#### `POST /api/v1/ai/anomalies/detect`
- **Auth**: None (Public / Scheduled Trigger)
- **Description**: Dispatches the asynchronous Celery job to calculate Z-scores and evaluate rate anomalies.
- **cURL Example**:
  ```bash
  curl -X POST http://localhost:8000/api/v1/ai/anomalies/detect
  ```

#### `GET /api/v1/ai/trends/{trade_lane}`
- **Auth**: None (Public)
- **Path Parameters**:
  - `trade_lane` (*string, required*): e.g. `CNSHA-EGPSD`
- **Description**: Returns the statistical trend metrics, R² goodness-of-fit, anomaly status, and AI recommendation text.
- **cURL Example**:
  ```bash
  curl -X GET http://localhost:8000/api/v1/ai/trends/CNSHA-EGPSD
  ```

#### `GET /api/v1/ai/alerts`
- **Auth**: None (Public)
- **Query Parameters**:
  - `unread_only` (*boolean, optional, default: `false`*)
  - `limit` (*integer, optional, default: `50`*)
- **cURL Example**:
  ```bash
  curl -X GET "http://localhost:8000/api/v1/ai/alerts?unread_only=true&limit=20"
  ```

#### `PUT /api/v1/ai/alerts/{alert_id}/read`
- **Auth**: None (Public)
- **Path Parameters**:
  - `alert_id` (*string / UUID, required*)
- **cURL Example**:
  ```bash
  curl -X PUT http://localhost:8000/api/v1/ai/alerts/3fa85f64-5717-4562-b3fc-2c963f66afa6/read
  ```

---

### 10. Real-Time WebSockets

#### `WS /api/v1/ws/alerts/{user_id}`
- **Auth**: 🔒 **Required** (`X-API-Key` in WebSocket connection headers)
- **Path Parameters**:
  - `user_id` (*UUID / string, required*): The target user ID channel.
- **Description**: Opens a persistent WebSocket connection that subscribes to the user's Redis alert channel (`alerts:{user_id}`) and pushes JSON notifications in real time whenever rate anomalies or custom alert rules fire.
- **WebSocket Connection (JavaScript Example)**:
  ```javascript
  const userId = "c1f75322-8321-4f3b-871d-66e2c20a9911";
  const apiKey = "dev_local_api_key_123";

  const ws = new WebSocket(`ws://localhost:8000/api/v1/ws/alerts/${userId}`, {
    headers: {
      "X-API-Key": apiKey
    }
  });

  ws.onmessage = (event) => {
    const alert = JSON.parse(event.data);
    console.log("Real-time alert received:", alert);
  };
  ```
- **Pushed Message Payload**:
  ```json
  {
    "id": "7b79a5c8-18e4-4d82-b7b5-0c6f1a8e1b12",
    "alert_type": "rate_spike",
    "trade_lane": "CNSHA-EGPSD",
    "message": "Rate on CNSHA-EGPSD spiked by +12.4% over 7 days",
    "magnitude_pct": 12.4,
    "timestamp": "2026-08-20T23:58:00Z"
  }
  ```

---

### 11. Users & Authentication Profiles

#### `GET /api/v1/users`
- **Auth**: 🔒 **Required** (`X-API-Key`)
- **Query Parameters**:
  - `is_admin` (*boolean, optional*): Filter by admin status (`true` / `false`).
  - `limit` (*integer, optional, default: `100`*): Max number of users to return.
  - `offset` (*integer, optional, default: `0`*): Pagination offset.
- **Description**: Returns all registered users in descending order of registration.
- **cURL Example**:
  ```bash
  curl -X GET http://localhost:8000/api/v1/users \
    -H "X-API-Key: dev_local_api_key_123"
  ```
- **Response `200 OK`**:
  ```json
  [
    {
      "id": "c1f75322-8321-4f3b-871d-66e2c20a9911",
      "email": "demo@freightpulse.test",
      "is_admin": false,
      "created_at": "2026-08-21T00:00:00Z",
      "updated_at": "2026-08-21T00:00:00Z"
    },
    {
      "id": "7b79a5c8-18e4-4d82-b7b5-0c6f1a8e1b12",
      "email": "admin@freightpulse.test",
      "is_admin": true,
      "created_at": "2026-08-21T00:00:00Z",
      "updated_at": "2026-08-21T00:00:00Z"
    }
  ]
  ```

#### `GET /api/v1/users/me`
- **Auth**: 🔒 **Required** (`X-API-Key`)
- **Description**: Retrieves the profile and authorization level of the currently authenticated user.
- **cURL Example**:
  ```bash
  curl -X GET http://localhost:8000/api/v1/users/me \
    -H "X-API-Key: dev_local_api_key_123"
  ```
- **Response `200 OK`**:
  ```json
  {
    "id": "7b79a5c8-18e4-4d82-b7b5-0c6f1a8e1b12",
    "email": "admin@freightpulse.ai",
    "is_admin": true,
    "created_at": "2026-08-21T00:00:00Z",
    "updated_at": "2026-08-21T00:00:00Z"
  }
  ```

#### `GET /api/v1/users/{user_id}`
- **Auth**: 🔒 **Required** (`X-API-Key`)
- **Path Parameters**:
  - `user_id` (*UUID, required*): The user's UUID.
- **cURL Example**:
  ```bash
  curl -X GET http://localhost:8000/api/v1/users/c1f75322-8321-4f3b-871d-66e2c20a9911 \
    -H "X-API-Key: dev_local_api_key_123"
  ```

---

## 🛠️ Local Development & Running

### 1. Start Services via Docker Compose
```bash
docker compose up -d --build
```

### 2. Run Database Migrations
```bash
docker compose exec backend alembic upgrade head
```

### 3. Run Test Suite
```bash
docker compose exec backend pytest
```
