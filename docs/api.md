# Norman REST API — for Carl-IOS

The FastAPI service (`apps/api`) auto-generates an OpenAPI spec. Carl-IOS uses it as its source of truth and codegens a Swift client.

## Endpoints

- `GET    /health` — liveness probe, no auth.
- `POST   /v1/auth/register` — email + password → 201.
- `POST   /v1/auth/login`    — email + password → `{ access_token, token_type }`. JWT bearer.
- `GET    /v1/hubs` — list hubs the authenticated user owns.
- `POST   /v1/hubs` — register a new hub (returns hub_id; pair with firmware out-of-band).
- `GET    /v1/hubs/{hub_id}/sensors` — list sensors that have reported under a hub.
- `GET    /v1/sensors/{sensor_id}/latest` — the most recent reading per metric.
- `GET    /v1/sensors/{sensor_id}/readings?from=&to=&metric=&interval=` — time series; `interval` (e.g. `5m`, `1h`) downsamples via TimescaleDB `time_bucket`.
- `GET    /v1/predictions/{hub_id}` — most recent ML output for the hub. Returns `null` payloads until the ML pipeline lands.

## Auth

JWT bearer. `Authorization: Bearer <token>`. Tokens expire per `JWT_EXPIRE_MINUTES` (default 24h).

## Spec

- Live: `http://localhost:8000/openapi.json`
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

To codegen a Swift client:

```bash
# from Carl-IOS repo, against a running local Norman
swift package init --type tool # or use OpenAPIGenerator
# point its config at http://localhost:8000/openapi.json
```
