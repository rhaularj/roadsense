# Deploying RoadSense

This guide takes RoadSense from the laptop demo to a pilot deployment. Everything below is configuration; the
Trust & system page shows which settings are still development defaults.

## 1. Architecture

```
 dashcam / phone ──► web app :7860 (sign-in, roles, edge pipeline for uploads) ──► agent API :8000
                                                                                     │  durable jobs + scheduler
                                                                                     │  4 MCP servers (stdio)
                                                                                     ▼
                                       road authority ◄── delivery adapters: open311 · cityworks · arcgis · referral
                                       (fetches the evidence photo through a signed /media link)
```

Expose only two things publicly, behind TLS: the web app, and `GET /media/*` of the agent API. Example Caddyfile:

```
roadsense.example.ca {
    reverse_proxy 127.0.0.1:7860
}
media.roadsense.example.ca {
    @media path /media/*
    reverse_proxy @media 127.0.0.1:8000
    respond 404
}
```

Then set `ROADSENSE_PUBLIC_URL=https://media.roadsense.example.ca`, `ROADSENSE_COOKIE_SECURE=1` and
`ROADSENSE_OIDC_REDIRECT_URL=https://roadsense.example.ca/auth/oidc/callback`.

## 2. Secrets

```
python -c "import secrets; print(secrets.token_urlsafe(48))"   # run once for each
```

`ROADSENSE_API_TOKEN`, `ROADSENSE_SESSION_SECRET`, `ROADSENSE_MEDIA_SECRET`, `ROADSENSE_OPEN311_API_KEY`. Keep them in
the host's secret store, not in the image. Rotating `ROADSENSE_MEDIA_SECRET` invalidates evidence links that were
already sent, so rotate it only between pilots.

## 3. Sign-in

- First start creates `ROADSENSE_ADMIN_EMAIL`. Without `ROADSENSE_ADMIN_PASSWORD`, a random password is written to
  `<data>/initial_admin_password.txt`. Sign in, change it, then delete the file.
- Single sign-on with Microsoft Entra ID: register an app with the redirect URL above, then set
  `ROADSENSE_OIDC_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0`, `ROADSENSE_OIDC_CLIENT_ID` and
  `ROADSENSE_OIDC_CLIENT_SECRET`. Define app roles named `admin`, `reviewer`, `driver` and `viewer` in Entra and assign
  them to groups; the role claim is applied at every sign-in. Users without a role claim get
  `ROADSENSE_OIDC_DEFAULT_ROLE` (viewer).

## 4. Data residency (Nova Scotia)

Host the container and its volume in a Canadian region. Set:

```
OPENROUTER_BASE_URL=https://<canadian-openai-compatible-endpoint>/v1
ROADSENSE_LLM_MODELS=<model ids available there>
ROADSENSE_DATA_RESIDENCY=ca
ROADSENSE_RESIDENCY_LLM_HOSTS=<that host name>
ROADSENSE_OSRM_URL=https://<your OSRM>        # and ROADSENSE_NOMINATIM_URL
```

With residency enforced, a misconfigured LLM host makes the agents stop and the deterministic pipeline finish the
work; no prompt leaves the allow-list.

## 5. City systems

| Step | Setting | Needs from the city |
|---|---|---|
| Read the city's own service requests (dedupe, closures) | `ROADSENSE_CITY_SR_LAYER_URL` = an ArcGIS FeatureServer layer URL; optional `ROADSENSE_CITY_SR_WHERE` | nothing: HRM publishes Cityworks SRs on its ArcGIS Hub open-data portal |
| File into Cityworks | authority `"channel": "cityworks"` plus `cityworks_problem_sid` in the authorities file; `ROADSENSE_CITYWORKS_URL/_USER/_PASSWORD` | an integration ("API only") user and the pothole problem code |
| File into an ArcGIS layer | `"channel": "arcgis"` plus `arcgis_fields`; `ROADSENSE_ARCGIS_LAYER_URL`, `ROADSENSE_ARCGIS_TOKEN` | an editable hosted feature layer |
| Open311 GeoReport v2 | `"channel": "open311"`, `open311_url`, `ROADSENSE_OPEN311_API_KEY` | an API key |
| Referral by email (NS Public Works) | `"channel": "referral"`, `referral_email`; `ROADSENSE_SMTP_*` | an inbox that accepts referrals |

Copy `roadsense/core/municipalities.json`, edit it, and point `ROADSENSE_AUTHORITIES_FILE` at the copy. The `_rules`
block holds the region's routing and triage rules (provincial routes, Priority 1 width, severity bands, repair
targets by road class), so another region is a new file, not a code change. Validate field names against the city's
test instance before switching a channel; the adapters are tested against the vendors' published API shapes, not
against HRM's instance.

## 6. Third-party feeds (aggregator mode)

`POST /external/detections` (service token) takes `{"source": "samsara", "items": [{"id", "lat", "lon", ...}]}` and
`POST /external/waze` takes a Waze for Cities alerts feed. Third-party sightings never become reports on their own;
they corroborate RoadSense reports at the same spot and are shown to the reviewer.

## 7. Operations

- Health: `GET /health` (agent API). Docker has a `HEALTHCHECK`.
- Metrics: `GET /metrics` on the agent API (service token) and the web app (admin session), Prometheus text format:
  request counts and latency, job outcomes, reports and events by status, delivery failures.
- Logs: one JSON line per request with a request id (`X-Request-ID` is returned on every response).
- Jobs survive restarts. The scheduler retries deliveries, pushes updates, runs follow-up every
  `ROADSENSE_FOLLOW_UP_MINUTES`, syncs city requests and applies retention hourly.
- Backups: the data volume holds the SQLite database (WAL mode) and the evidence photos. Back up with
  `sqlite3 roadsense.db ".backup backup.db"` plus the `media/` folder.

## 8. Ground truth

Every approve, reject and class correction is stored as a label. `python scripts/export_labels.py` writes a YOLO
dataset of the privacy-redacted frames (split by trip) for fine-tuning on Halifax conditions, and a CSV of the
decisions for measuring real-world precision.

## Known limits

- One process per service and SQLite: fine for a pilot of a few vehicles, not for a city-wide fleet. Moving to
  Postgres/PostGIS and object storage is the next scaling step.
- The capture side is the laptop/web upload; there is no in-vehicle app or fleet kit yet.
- The condition index is an estimate from detected defects, not a certified pavement survey.
