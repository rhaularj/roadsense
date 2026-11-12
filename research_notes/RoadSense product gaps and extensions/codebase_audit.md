# RoadSense codebase audit: current capabilities and gaps (branch feature/saas-ui-revamp, commit 04e1db7, Nov 2026)

Scope: the repository only (read-only). All citations are `path:line` in the worktree `D:/py/roadsense/.claude/worktrees/roadsense-ui-revamp-3484d5`. Size: about 8.3k tracked lines; Python packages `common`, `core`, `edge`, `mcp_servers`, `agents`, `services`, `web`; 41 pytest tests; 8 commits. Line numbers are from `cat -n` of each file.

## Q1. What are the end-to-end capabilities, data model and integrations actually implemented (vs. mocked or stubbed)?

### Takeaway
The whole pipeline runs for real on one laptop: video plus GPS, then YOLOv8m with BoT-SORT tracking, best-frame selection, on-device blur and flat-road geo-projection, then an outbox upload with a token, OSRM road snapping, four stdio MCP servers, an OpenRouter orchestrator with five specialists, deterministic rules, hash-locked driver approval, and delivery. Only the last hop is fake. "Halifax 311" is a local mock GeoReport v2 server, and the province gets a JSON file written to disk. The data model is four SQLite tables plus a cache. It has no users, drivers, vehicles, tenants or authorities as entities.

### Cited Findings
**Edge (Level 1)**
- The video is sampled at 5 fps by default (stride = video_fps/sample_fps). Ultralytics tracking uses a custom BoT-SORT config, and an optional `roi_top` sky crop is off by default — [roadsense/edge/process_video.py:58-104](roadsense/edge/process_video.py), [README.md:119](README.md)
- Track aggregation emits one event per physical defect once the track has been gone for `max_gap_s`. A track is accepted if it was seen in at least 3 frames, or in 2 or more frames with confidence ≥0.5. The best frame maximises confidence × sharpness (Laplacian variance, saturating at 300). Class is a majority vote — [roadsense/edge/tracker.py:19-21](roadsense/edge/tracker.py), [roadsense/edge/tracker.py:38-40](roadsense/edge/tracker.py), [roadsense/edge/tracker.py:73-74](roadsense/edge/tracker.py)
- Redaction downsamples the frame 8× and applies a Gaussian blur (k=41) to everything outside the damage box plus a 15% margin. It uses no face or plate detector — [roadsense/edge/redact.py:1-20](roadsense/edge/redact.py)
- Geometry is a flat-road pinhole model. Distances over 40 m are untrusted. Position uncertainty is set to 6 m of GPS error plus 0.15 × distance, which the code itself labels "inference, not measured". Camera height, pitch and HFOV are env defaults (1.3 m, 3°, 110°) — [roadsense/edge/camera.py:17-18](roadsense/edge/camera.py), [roadsense/edge/camera.py:22-25](roadsense/edge/camera.py), [roadsense/edge/camera.py:50-52](roadsense/edge/camera.py)
- GPS accepts GPX or CSV (time,lat,lon) and interpolates linearly. Heading is the bearing between bracketing fixes. Video-to-GPS alignment is a manual `--gps-offset` only — [roadsense/edge/gps.py:53-79](roadsense/edge/gps.py), [roadsense/edge/process_video.py:129](roadsense/edge/process_video.py)
- The outbox is store-and-forward: one JSON + JPEG per event, moved to `sent/` once the API accepts it, with no retry scheduler — [roadsense/edge/outbox.py:16-36](roadsense/edge/outbox.py)
- The edge-to-API contract is a pydantic `DamageEvent` with a regex on the id, coordinate ranges, a class whitelist (D00/D10/D20/D40) and bounds on distance and width — [roadsense/common/schemas.py:13-41](roadsense/common/schemas.py)

**Models**
- There are 4 RDD2022 classes. The thresholds were tuned on the validation split: YOLOv8m conf 0.25 (F1 0.590), RT-DETR-L conf 0.50 (F1 0.614), and YOLOv8s is listed — [roadsense/common/detectors.py:14-27](roadsense/common/detectors.py)
- The weights are not in the repo (`weights/`, `*.pt` are gitignored) and come from a separate training repo — [.gitignore:7-8](.gitignore), [README.md:151](README.md)

**Agent API and agents (Level 2)**
- The FastAPI agent API takes `POST /events` (bearer token, JPEG magic bytes, 5 MB cap), snaps each event to the road with OSRM, and queues jobs to one in-process worker — [roadsense/services/agent_api.py:33](roadsense/services/agent_api.py), [roadsense/services/agent_api.py:121-148](roadsense/services/agent_api.py), [roadsense/services/agent_api.py:36-77](roadsense/services/agent_api.py)
- There are four FastMCP stdio servers (detector, geo, reports, municipality), each started as a subprocess by `Toolbox` — [roadsense/agents/mcp_client.py:14-41](roadsense/agents/mcp_client.py)
- The orchestrator sees specialists only as `delegate_to_*` tools. While a trip is processed, the filing agent is limited to drafting tools — [roadsense/agents/orchestrator.py:99-105](roadsense/agents/orchestrator.py), [roadsense/agents/orchestrator.py:125-130](roadsense/agents/orchestrator.py)
- The specialists are vision, location, triage, filing and follow_up. Each has a tool allow-list and a pydantic output contract, and gets one self-correction — [roadsense/agents/specialists.py:28-77](roadsense/agents/specialists.py), [roadsense/agents/contracts.py:13-74](roadsense/agents/orchestrator.py), [roadsense/agents/orchestrator.py:63-75](roadsense/agents/orchestrator.py)
- The deterministic fallback (`complete_trip`) runs after every agent run and finishes any undecided events — [roadsense/agents/fallback.py:41-54](roadsense/agents/fallback.py), [roadsense/agents/orchestrator.py:143](roadsense/agents/orchestrator.py)
- The LLM client calls OpenRouter with a `models` fallback array and `require_parameters`, a token bucket (15 RPM default), Retry-After handling, a call budget of 40, and `live|cache|replay` modes backed by a SQLite cache — [roadsense/agents/llm.py:1-121](roadsense/agents/llm.py), [roadsense/common/config.py:50-51](roadsense/common/config.py)

**Rules engine**
- Verdict: suggested from verifier confidence or close-up re-check. "Confirmed" or "disputed" is refused without verifier evidence — [roadsense/core/reports.py:22-56](roadsense/core/reports.py)
- Severity: pothole width ≥25 cm makes it an HRM "Priority 1 candidate" (depth is not measurable). Otherwise severity comes from box-area ratio — [roadsense/core/reports.py:19](roadsense/core/reports.py), [roadsense/core/reports.py:59-81](roadsense/core/reports.py)
- Priority = severity weight × class weight × (1 + ln confirmations) — [roadsense/core/reports.py:84-85](roadsense/core/reports.py)
- Dedupe: same class, open status, within 15 m (bounding box in SQL, then haversine). Confirmations count distinct trips — [roadsense/core/reports.py:88-148](roadsense/core/reports.py)
- Jurisdiction: 100-series or motorway goes to the province (high). Other numbered or trunk routes are ambiguous (medium/medium). Everything else goes to the municipality — [roadsense/core/geo.py:130-149](roadsense/core/geo.py)

**Delivery, approval and data model**
- Approval: the payload is built deterministically from the DB. The driver posts the SHA-256 they saw, and the API checks it with `compare_digest` and stores it. Submission re-hashes and refuses on a mismatch — [roadsense/core/open311.py:45-60](roadsense/core/open311.py), [roadsense/services/agent_api.py:278-288](roadsense/services/agent_api.py), [roadsense/mcp_servers/municipality_server.py:37-44](roadsense/mcp_servers/municipality_server.py)
- Delivery: Open311 is a form POST to `{open311_url}/requests.json` with an `api_key`. The "referral" channel writes `data/referrals/REF-<hash>.json` and nothing is transmitted — [roadsense/core/open311.py:63-84](roadsense/core/open311.py)
- Follow-up: the agent polls `GET /requests/{id}.json`, and "closed" marks the report fixed. Referral reports have no status feed — [roadsense/core/open311.py:87-93](roadsense/core/open311.py), [roadsense/mcp_servers/municipality_server.py:55-71](roadsense/mcp_servers/municipality_server.py)
- Data model: tables `events`, `reports`, `audit` (append-only by trigger), `notifications`, `geocache`, plus `llm_cache`. Additive `ALTER TABLE` migrations run on every connect. Report statuses are pending_approval/approved/rejected/submitted/fixed — [roadsense/common/db.py:12-87](roadsense/common/db.py), [roadsense/common/db.py:101-106](roadsense/common/db.py), [roadsense/agents/llm.py:25](roadsense/agents/llm.py)

**Web app**
- The web app is a FastAPI backend-for-frontend on :7860. It holds the token and forwards a fixed set of calls. It also runs the edge pipeline on uploaded videos in a background thread, behind a GPU lock — [roadsense/web/app.py:1-56](roadsense/web/app.py), [roadsense/web/app.py:178-232](roadsense/web/app.py)
- The SPA is vanilla JS with vendored Leaflet. Pages: Overview, Trips, Review, Reports, Map, Agent activity, Authorities, Trust & system. It has a command palette and J/K inbox navigation — [README.md:163-179](README.md), [docs/design-system.md](docs/design-system.md)

**Real vs mocked, as the README states it**
- Real: models, verification, tracking, redaction, geometry, Nominatim, OSRM snapping, MCP and the agent loop. Mocked: test videos (RDD2022 stills with simulated motion), the offline fixture of two roads, the public OSRM demo server, the Open311 mock ("HRM has no public Open311 API"), the referral JSON, and uncalibrated camera defaults — [README.md:121-131](README.md), [roadsense/core/municipalities.json:10](roadsense/core/municipalities.json)

### Inferences
- The defensible core is the guarded decision layer: verdict guard, idempotent merge, hash-locked payload, and an allow-list enforced in the loop. The LLM layer is mostly a narrator over deterministic MCP tools. Severity and P1 are rule outputs, and the fallback finishes anything the agents skip.
- Everything past "approved" is a demo. No authority is actually reached, so "time to repair" and "accepted by city" outcomes cannot be measured.

### Gaps
- No calibration data, real Halifax footage or measured widths are in the repo, so I could not verify edge geometry accuracy (README roadmap: [README.md:223](README.md)).
- I did not read the detector training repo, so I could not verify training data provenance or licence beyond the README claims.

## Q2. What is mocked or hard-coded and blocks real deployment?

### Takeaway
RoadSense is hard-wired to one region and two authorities. It runs on public free-tier infrastructure (OSM Nominatim, the OSRM demo server, OpenRouter free models). The 311 endpoint is a mock, and the media URL the city would receive points at localhost. Demo and simulated data paths are on by default in the upload UI.

### Cited Findings
- The authority directory is a static JSON with exactly two entries: HRM (open311, but to the mock URL) and NS Public Works (referral). The aliases are Halifax communities — [roadsense/core/municipalities.json:1-18](roadsense/core/municipalities.json)
- The offline geocoder knows one bounding box (HRM) and two hand-typed road segments, Highway 102 and Bedford Highway. It is used whenever `ROADSENSE_OFFLINE_GEO=1`, or for 120 s after any Nominatim failure — [roadsense/core/geo.py:15-27](roadsense/core/geo.py), [roadsense/core/geo.py:64-65](roadsense/core/geo.py), [roadsense/core/geo.py:88-90](roadsense/core/geo.py)
- Jurisdiction logic is Nova Scotia-specific ("100-series highways"), and the provincial authority name is hard-coded as `PROVINCIAL = "Nova Scotia Public Works"` — [roadsense/core/geo.py:22](roadsense/core/geo.py), [roadsense/core/geo.py:138-141](roadsense/core/geo.py). The summary counts provincial reports with `jurisdiction LIKE 'Nova Scotia%'` — [roadsense/agents/fallback.py:67](roadsense/agents/fallback.py)
- Prompts embed NS rules and model F1 numbers in their text: "100-series highways are provincial (Nova Scotia Public Works)" — [roadsense/agents/specialists.py:45-47](roadsense/agents/specialists.py), [roadsense/agents/specialists.py:31-33](roadsense/agents/specialists.py)
- Severity uses the HRM Priority 1 width (25 cm) as a constant — [roadsense/core/reports.py:19](roadsense/core/reports.py)
- Service codes `POTHOLE` and `ROAD_SURFACE` are invented for the mock and are not HRM's taxonomy — [roadsense/services/mock_open311.py:21-26](roadsense/services/mock_open311.py), [roadsense/core/municipalities.json:6-7](roadsense/core/municipalities.json)
- `media_url` in the payload is `{agent_api_url}/media/{id}.jpg`, default `http://127.0.0.1:8000`. A real 311 system could not fetch it. The media endpoint is also unauthenticated — [roadsense/core/open311.py:54](roadsense/core/open311.py), [roadsense/common/config.py:41](roadsense/common/config.py), [roadsense/services/agent_api.py:316-324](roadsense/services/agent_api.py)
- External services default to public endpoints: the Nominatim public API (1 req/s policy), `router.project-osrm.org` ("for development; run your own for a pilot"), and a "student hackathon project" user agent — [roadsense/common/config.py:54-58](roadsense/common/config.py), [README.md:127](README.md)
- The LLM defaults are three `:free` OpenRouter models, with a 50 requests/day budget (1,000 after $10 of credit). A 15-event trip uses about 19 requests — [roadsense/common/config.py:15-19](roadsense/common/config.py), [README.md:113-115](README.md)
- The web upload form defaults to a simulated GPS track along a fixed Halifax route (`simulate: bool = Form(True)`). A GPS file is only used when the user turns simulation off — [roadsense/web/app.py:208](roadsense/web/app.py), [roadsense/web/app.py:223](roadsense/web/app.py), [roadsense/web/app.py:169-175](roadsense/web/app.py)
- Evaluation and demo data are RDD2022 stills from China, Japan and the US, placed at Halifax coordinates (e.g. demo-03 "Highway 102" is `Japan_008319.jpg`) — [demo/trip/manifest.json:1-32](demo/trip/manifest.json), [scripts/build_demo_trip.py:65-73](scripts/build_demo_trip.py)
- The default secrets are `dev-token-change-me` and `dev-open311-key`, and the code ships them as fallbacks — [roadsense/common/config.py:42-44](roadsense/common/config.py), [.env.example:15-16](.env.example)
- The verifier silently falls back to the edge weights if the RT-DETR file is missing. The "second opinion" then comes from the same model family/weights — [roadsense/mcp_servers/detector_server.py:24-29](roadsense/mcp_servers/detector_server.py)
- Docker: a CPU-only image runs all three services in one container via `run_all.py --host 0.0.0.0`. The README says it is "not yet tested here" — [Dockerfile:3-19](Dockerfile), [README.md:161](README.md)

### Inferences
- Taking RoadSense to another city or province means changing code (geo rules, prompts, constants, directory), not just configuration. A per-tenant authority directory with polygons, service codes and rules is the main architectural gap.
- The mock-to-real gap for Halifax is twofold: integration (HRM has no public Open311 API, so delivery would need a partner channel, email, or a 311-staff portal) and a reachable, access-controlled media host.

### Gaps
- The repo does not show what interface HRM 311 or NS Public Works would actually accept. Only contact strings are given — [roadsense/core/municipalities.json:9](roadsense/core/municipalities.json), [roadsense/core/municipalities.json:15](roadsense/core/municipalities.json).

## Q3. What is missing for production (multi-tenancy, auth, RBAC, real 311, job queue, storage, observability, CI, packaging, mobile capture, scale)?

### Takeaway
RoadSense is a single-user, single-process laptop system. It has one shared bearer token, no user or driver identity, and in-memory job state. SQLite plus local files hold everything, and four MCP subprocesses run per worker. It has no CI, no metrics or tracing, and no mobile capture app. Several read endpoints, and the entire web UI, are unauthenticated.

### Cited Findings
**Identity and authorization**
- There is one static bearer token for everything. The rate limiter keys on client IP in an in-process dict — [roadsense/services/agent_api.py:93-105](roadsense/services/agent_api.py)
- Unauthenticated agent-API endpoints: `/jobs/{id}`, `/trips/{id}/events`, `/events/{id}`, `/stats`, `/trips`, `/reports/{id}` (includes the full audit trail), `/trips/{id}/reports`, `/reports`, `/reports/{id}/payload`, `/notifications`, `/media/{id}.jpg`. Only `/llm/status`, `POST /events`, process, approve, reject, follow-up and `/audit` require the token — [roadsense/services/agent_api.py:157-324](roadsense/services/agent_api.py)
- The web app has no login at all, so anyone who reaches :7860 can approve, reject, upload or trigger follow-up. The SECURITY doc relies on "binds to localhost by default", but the Dockerfile binds 0.0.0.0 and publishes the ports — [roadsense/web/app.py:121-140](roadsense/web/app.py), [SECURITY.md:41](SECURITY.md), [Dockerfile:18-19](Dockerfile), [docker-compose.yml:13-16](docker-compose.yml)
- Approvals are recorded with actor `"driver"` hard-coded. There is no per-driver ownership: any token holder can approve any report, including another driver's — [roadsense/services/agent_api.py:286](roadsense/services/agent_api.py)
- Schema: no users, drivers, vehicles, fleets or tenants tables. `notifications` has only `report_id` and `message`, so "tell each driver" is in fact one row per report, shown to everyone — [roadsense/common/db.py:60-65](roadsense/common/db.py), [roadsense/mcp_servers/reports_server.py:120-130](roadsense/mcp_servers/reports_server.py)
- The research synthesis itself defers a "separate city workspace with its own login and queue (post-hackathon)" — [docs/research-synthesis.md:114](docs/research-synthesis.md)

**Jobs, concurrency and scale**
- One `asyncio.Queue` worker runs jobs strictly one at a time. Job state is a Python dict, lost on restart. The web app keeps a second in-memory `jobs` dict and runs edge jobs in daemon threads under one GPU lock — [roadsense/services/agent_api.py:36-77](roadsense/services/agent_api.py), [roadsense/web/app.py:36-37](roadsense/web/app.py), [roadsense/web/app.py:231](roadsense/web/app.py)
- `POST /trips/{id}/process` and `/approve` block by default (wait up to 600 s or 300 s). An approval queues behind any running trip. A live LLM trip took 214 s — [roadsense/services/agent_api.py:151-154](roadsense/services/agent_api.py), [roadsense/services/agent_api.py:287-288](roadsense/services/agent_api.py), [results/agent_eval_llm.json:20-23](results/agent_eval_llm.json)
- The trip id comes from wall-clock seconds (`trip%Y%m%d-%H%M%S`), so two uploads in the same second collide — [roadsense/web/app.py:211](roadsense/web/app.py)
- MCP over stdio means four Python subprocesses per Toolbox, and an MCP session is bound to one task. Horizontal scaling (Postgres+PostGIS, job queue, Streamable HTTP MCP, Canadian hosting) is roadmap only — [roadsense/agents/mcp_client.py:22-41](roadsense/agents/mcp_client.py), [README.md:225](README.md)

**Storage**
- SQLite in WAL mode is shared by separate processes. Media sits on local disk under `data/media`, referrals under `data/referrals` and uploads under `data/uploads/<trip>`. There is no retention or deletion policy anywhere — [roadsense/common/db.py:1](roadsense/common/db.py), [roadsense/common/config.py:62-68](roadsense/common/config.py), [roadsense/web/app.py:212-221](roadsense/web/app.py)
- The geocache key is lat/lon rounded to 4 decimals (about 10 m cells), with no TTL. Spatial queries scan a lat/lon bounding box with no spatial index — [roadsense/core/geo.py:60](roadsense/core/geo.py), [roadsense/core/reports.py:88-103](roadsense/core/reports.py)

**Delivery robustness**
- There is no retry or dead-letter queue for delivery. If `city_submit_request` fails, the report stays `approved`. `_pending` rejects anything not `pending_approval`, so the UI cannot re-approve it, and no "resend" endpoint exists — [roadsense/mcp_servers/municipality_server.py:45-48](roadsense/mcp_servers/municipality_server.py), [roadsense/services/agent_api.py:258-264](roadsense/services/agent_api.py)
- Merges keep updating reports in `approved` and `submitted` state (`OPEN_STATUSES`). A merge into an approved, not-yet-sent report changes confirmations and severity, so the payload hash no longer matches and sending is refused permanently. A merge into a submitted report is never pushed to the city — [roadsense/core/reports.py:17](roadsense/core/reports.py), [roadsense/core/reports.py:124-134](roadsense/core/reports.py), [roadsense/mcp_servers/municipality_server.py:41-44](roadsense/mcp_servers/municipality_server.py)
- Follow-up is manual: a button or `POST /follow-up`. No scheduler exists — [roadsense/services/agent_api.py:298-301](roadsense/services/agent_api.py), [roadsense/web/static/app.js:544](roadsense/web/static/app.js)

**Observability, CI and packaging**
- Observability is limited to the SQLite audit table plus `logging.basicConfig`. There are no metrics endpoint, tracing, log shipping or alerting — [roadsense/common/db.py:124-127](roadsense/common/db.py), [roadsense/services/agent_api.py:334](roadsense/services/agent_api.py)
- No CI: there is no `.github/` directory. Quality gates run by hand via `scripts/check.py`, which skips ruff and pip-audit when they are not installed — [scripts/check.py:21-33](scripts/check.py)
- Packaging: `pyproject.toml` has no dependencies, entry points or build backend. `requirements.txt` is mostly unpinned (`opencv-python`, `numpy`, `fastapi`, `uvicorn`, `httpx`, `pytest`), even though SECURITY.md claims "Dependencies are pinned" — [pyproject.toml:1-5](pyproject.toml), [requirements.txt:1-24](requirements.txt), [SECURITY.md:27](SECURITY.md)
- README says "38 tests", but the repo has 41 `def test_` functions — [README.md:196](README.md)

**Capture**
- No mobile or dashcam capture client exists. The "edge device" is the laptop or web server processing an uploaded file. Real-time capture, phone GPS logging and an in-car UI are absent. The roadmap item is "Recorded Halifax drive with a phone GPS log" — [roadsense/web/app.py:5-6](roadsense/web/app.py), [README.md:223](README.md)

### Inferences
- The minimum pilot-grade backlog is: authN/authZ with driver, fleet and city roles; a durable job queue; Postgres/PostGIS with object storage and signed media URLs; delivery retry and a resend path; a scheduled follow-up; CI with pinned locks; and a capture app.

### Gaps
- No load, throughput or soak testing exists, so concurrency limits beyond "one job at a time" are unmeasured.

## Q4. What do TODOs, known limitations, README future work, eval results and the security model say?

### Takeaway
The code has no TODO or FIXME markers, but the authors document their limits openly. The verifier gain is modest. False-alarm rejection in the agent eval is weak (17-20%). The headline 100% results come from synthetic, fixture-based scenarios. The security model is solid for agent-level risks, but several of its claims are stronger than the deployment reality.

### Cited Findings
- A grep for TODO/FIXME/XXX/HACK across `roadsense`, `scripts` and `tests` returns nothing relevant. The only hits are the "student hackathon" user agent and UI placeholders — [roadsense/common/config.py:58](roadsense/common/config.py)
- README roadmap: keyless full-trip replay; a recorded Halifax drive with camera calibration and tape-measured widths; direction-aware dedupe (DBSCAN/H3) with "confirmed" only after two independent drivers; Postgres+PostGIS, a job queue, MCP over HTTP and Canadian hosting — [README.md:220-225](README.md)
- Verifier eval (350 test images, 568 labelled boxes): precision 0.714→0.744, 146 false alarms → 115 (−21%), true damage kept 92%, edge recall of labels only 0.641, and 12% of kept detections have a class dispute. The authors note both models share training data and blind spots — [results/verifier_eval.json:12-24](results/verifier_eval.json), [README.md:69-80](README.md)
- On validation, the tuned rule only removed 14.3% of false alarms — [results/verifier_rule.json:15](results/verifier_rule.json)
- Deterministic agent eval (42 scenarios): report precision 0.706, real damage reported 1.0, false alarms rejected 0.167 (2/12), jurisdiction 1.0, dedupe 1.0 — [results/agent_eval.json:1-36](results/agent_eval.json)
- LLM agent eval (17 scenarios, Nemotron free): false alarms rejected 0.2 (1/5), report precision 0.714, fallback 0%, 19 calls and about 102k tokens for a 15-event trip, 214 s per trip — [results/agent_eval_llm.json:1-46](results/agent_eval_llm.json)
- The orchestrator once miscounted severities in its driver summary. The LLM-written summary is still shown to the driver whenever it is not JSON — [README.md:110-111](README.md), [roadsense/agents/orchestrator.py:147-148](roadsense/agents/orchestrator.py)
- SECURITY.md is a student MVP with no external review. It maps OWASP Agentic ASI01/02/03/04/08/09/10, but not ASI05-07 — [SECURITY.md:5](SECURITY.md), [SECURITY.md:17-27](SECURITY.md)
- SECURITY.md says a privacy impact assessment and counsel review are needed before any pilot, and that a Canadian no-retention LLM provider is needed for municipal use (PIIDPA). The current defaults are free providers that "may log prompts" — [SECURITY.md:43-57](SECURITY.md)
- SECURITY.md says "Raw video never leaves the device". In the web flow, the full raw video is uploaded to the web server and kept indefinitely under `data/uploads/<trip>/video.*` — [SECURITY.md:11](SECURITY.md), [roadsense/web/app.py:212-221](roadsense/web/app.py)
- SECURITY.md says "Only frames that contain damage are uploaded, never the track". In the web flow, the GPS file (or a simulated GPX) is also written server-side — [SECURITY.md:12](SECURITY.md), [roadsense/web/app.py:185](roadsense/web/app.py), [roadsense/web/app.py:226-227](roadsense/web/app.py)
- Each event also carries `car_lat`/`car_lon` and `captured_at`, which together rebuild a partial timed trajectory per trip — [roadsense/common/schemas.py:28-31](roadsense/common/schemas.py)
- The research synthesis interviewed nobody, and several Halifax figures come via an aggregator. Its open questions include auto-send vs review, how 311 dispatchers triage, duplicate/provincial share, incentives, and review tolerance — [docs/research-synthesis.md:2-3](docs/research-synthesis.md), [docs/research-synthesis.md:116-129](docs/research-synthesis.md), [README.md:7-9](README.md)

### Inferences
- The honest headline is that RoadSense routes and dedupes reliably in a fixture world, but about 29% of the reports it creates are still false alarms (precision about 0.71). Driver approval is the real false-positive filter, which shifts work onto drivers and city staff.
- The privacy claims hold for the CLI edge path, but the SaaS web path breaks them. Either the edge pipeline has to run in-browser or on-device, or uploads need a retention policy and the SECURITY.md wording has to change.

### Gaps
- No human-labelled Halifax ground truth exists, so the real-world precision, recall and position accuracy of RoadSense are unknown.

## Q5. Where are the test-coverage gaps and the weak points in model accuracy or agent decisions?

### Takeaway
The 41 tests cover the guard rules well (verdict evidence, merge idempotency, hash lock, sanitising, allow-list, append-only audit). Several things have no tests: the video pipeline, the upload and approve HTTP flows, delivery, follow-up, the detector MCP server, and the front end beyond string greps. Decision weak spots: class-specific, direction-blind dedupe; a free-text jurisdiction the LLM can set; prompt-cache key collisions; and P1 that ignores depth.

### Cited Findings
**Test inventory**
- Counts per file: test_decisions 11, test_edge 8, test_llm 4, test_mcp 1, test_reports 7, test_services 3, test_web 7. Tests run offline with no LLM — [tests/conftest.py:4-7](tests/conftest.py)
- Untested: `process_video` end to end, `outbox.upload`, the agent API's `/approve`, `/reject`, `/process`, `/follow-up` and `/stats`, `open311.submit`/referral, `request_status`/follow-up, the detector MCP server (needs weights), `snap_to_road`, the Nominatim parse, the rate limiter, and web proxy actions. `test_mcp` exercises only the reports and geo servers — [tests/test_mcp.py:8](tests/test_mcp.py), [tests/test_services.py:28-38](tests/test_services.py)
- The front-end tests grep `app.js` for strings (`"const esc = "`, the absence of `$("#approve")?.click()`), with no DOM or browser testing — [tests/test_web.py:20-45](tests/test_web.py)
- The orchestrator loop is never tested with a stub through a full trip. Only the generic `run_agent` allow-list is — [tests/test_services.py:60-71](tests/test_services.py)

**Eval design weaknesses**
- Jurisdiction "100%" is scored against the same two-segment offline fixture that generates the answers (highway/Bedford points are interpolated on the fixture segments) — [scripts/eval_agents.py:88-104](scripts/eval_agents.py), [roadsense/core/geo.py:18-21](roadsense/core/geo.py)
- Duplicate scenarios reuse the same image and detection, offset about 4 m, so a merge is nearly guaranteed. Nothing tests two distinct potholes within 15 m, which would wrongly merge — [scripts/eval_agents.py:105-107](scripts/eval_agents.py)
- Only the top-1 detection per image is used, `frames_seen` is fixed at 4 and heading at 90° in eval and demo data. The tracker and geometry play no part in the agent eval — [scripts/eval_agents.py:79](scripts/eval_agents.py), [scripts/eval_agents.py:125-126](scripts/eval_agents.py), [scripts/build_demo_trip.py:80-83](scripts/build_demo_trip.py)
- The LLM eval is a single run of 17 scenarios with no repeats, variance or model comparison — [results/agent_eval_llm.json:1-46](results/agent_eval_llm.json)

**Decision weak points**
- Dedupe requires the same class code. A pothole seen as D40 by one driver and D20 by another (12% class disputes) creates two reports. Dedupe also ignores heading and lane — [roadsense/core/reports.py:95-97](roadsense/core/reports.py), [results/verifier_eval.json:22](results/verifier_eval.json)
- Fixed and rejected reports are excluded from dedupe, so a pothole the driver rejected is re-proposed on every later trip — [roadsense/core/reports.py:17](roadsense/core/reports.py)
- The location contract's `jurisdiction` is a free string (max 80 characters), not constrained to the tool's candidates. `reports_create_or_merge` stores whatever the agent passes when the directory has no match. That report then fails at send time ("no delivery channel") rather than at triage — [roadsense/agents/contracts.py:24-28](roadsense/agents/contracts.py), [roadsense/mcp_servers/reports_server.py:55-66](roadsense/mcp_servers/reports_server.py), [roadsense/core/open311.py:65-67](roadsense/core/open311.py)
- The agent-provided `severity` is accepted as long as it is a valid enum. The rule severity is computed but only used for `p1_candidate`, so the LLM can upgrade or downgrade severity and priority. Severity in `reports_create_or_merge` uses edge confidence, while `detector_severity` uses verified confidence — [roadsense/mcp_servers/reports_server.py:61-67](roadsense/mcp_servers/reports_server.py), [roadsense/mcp_servers/detector_server.py:94-96](roadsense/mcp_servers/detector_server.py)
- The vision agent may "overrule the suggested verdict only with a stated reason". The guard blocks confirming without evidence, but it does not block rejecting real damage — [roadsense/agents/specialists.py:37-38](roadsense/agents/specialists.py), [roadsense/core/reports.py:47-51](roadsense/core/reports.py)
- The LLM cache key strips every `"id": "..."` value and timestamp. The task text lists events as JSON with `"id"` keys, so two trips with identical other fields can share a cache entry and replay answers for the wrong event ids. The orchestrator's events JSON includes `"id"` — [roadsense/agents/llm.py:27](roadsense/agents/llm.py), [roadsense/agents/llm.py:51-53](roadsense/agents/llm.py), [roadsense/agents/orchestrator.py:112-123](roadsense/agents/orchestrator.py)
- Severity and P1: depth is never measured, so P1 is "width ≥25 cm" from an uncalibrated flat-road projection. Non-pothole severity relies on box-area ratio, which depends on distance from the camera — [roadsense/core/reports.py:59-76](roadsense/core/reports.py), [roadsense/edge/camera.py:3-6](roadsense/edge/camera.py)
- Ambiguous numbered routes always resolved to HRM in both evals. No ground truth exists for these cases, and the eval skips scoring them — [results/agent_eval.json:10-14](results/agent_eval.json), [scripts/eval_agents.py:143-144](scripts/eval_agents.py)
- `POST /events` writes the image file before the duplicate-id check, so a re-upload with the same id overwrites the stored evidence image of an existing event — [roadsense/services/agent_api.py:131-135](roadsense/services/agent_api.py)
- The server never checks that an uploaded frame was actually redacted. A modified or third-party client can upload unblurred frames, which are then served publicly via `/media` — [roadsense/services/agent_api.py:127-132](roadsense/services/agent_api.py), [roadsense/services/agent_api.py:316-324](roadsense/services/agent_api.py)
- Redaction keeps the box plus a 15% margin unblurred. Any plate, person or house number that overlaps the damage box survives — [roadsense/edge/redact.py:16-19](roadsense/edge/redact.py)

**UX gaps tied to decisions**
- Review offers only Approve or Reject per report. It has no batch approve (recommended in the research synthesis), no class correction for "disputed" items, and no edit of the draft text — [roadsense/web/static/app.js:360-379](roadsense/web/static/app.js), [docs/research-synthesis.md:91](docs/research-synthesis.md)
- No agent API endpoint exists to change a report's class, location or jurisdiction — [roadsense/services/agent_api.py:278-296](roadsense/services/agent_api.py)

### Inferences
- The highest-value test additions are: an end-to-end API test of approve → mock Open311 → follow-up → notify; a stubbed-LLM orchestrator trip; a dedupe test with neighbouring distinct defects and cross-class sightings; and redaction tests on real frames with plates and faces.
- The cheapest accuracy wins sit in the decision layer, not the models: constrain jurisdiction to the candidate enum, make rule severity authoritative (or log disagreements with the agent's), allow cross-class merging when the verifier class matches, and include ids in the cache key.

### Gaps
- The detector MCP server and the eval scripts need the weights and the RDD2022 dataset, which are not in the repo, so I could not re-run or verify the numbers.
- The audit table holds no labelled per-decision outcomes, so how often agents overrule the rule baseline cannot be measured from the repo.
