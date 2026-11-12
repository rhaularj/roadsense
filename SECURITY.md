# RoadSense security and privacy

RoadSense handles road imagery and location from drivers, runs LLM agents that call tools, and sends reports to
public authorities. This document lists the threats we design against and where each control lives in the code.
The controls are real and tested (`tests/`), but the system has not had an external security review or a privacy
impact assessment yet; both are required before a pilot with real drivers (see "Before a pilot").

## Threat model

| Asset | Threat | Control |
|---|---|---|
| Bystanders in dashcam frames | Faces, plates, house numbers leave the vehicle | Redaction on the device: everything outside the damage box is blurred (`edge/redact.py`). **The server does not trust that**: every uploaded frame is checked for sharp detail outside the damage area and re-redacted if it has any (`core/privacy.server_redact`); an optional face/plate model (EgoBlur, TorchScript) blurs faces or plates inside the damage area. |
| Raw video and GPS tracks | Trips reconstructed from stored uploads | The web upload path deletes the raw video and GPS track as soon as the edge step has run, also when a job fails (`web/app.py`, `core/privacy.delete_trip_raw`). Leftovers older than a day are purged hourly. `ROADSENSE_KEEP_RAW_VIDEO=1` is a development setting and raises a production warning. |
| Driver location history | Car position stored with each event | The car's own position is erased after `ROADSENSE_CAR_POSITION_DAYS` (30); photos of rejected detections after `ROADSENSE_REJECTED_MEDIA_DAYS` (30). The scheduler applies the policy hourly and logs each purge. |
| Evidence photos | Enumeration or hot-linking of `/media` | `/media` needs the service token or an HMAC-signed link with an expiry (`core/media.py`). The expiry is derived from the report's creation time, so the approved payload hash is stable. |
| Report pipeline | Forged or malformed uploads | Bearer token on **every** agent API endpoint except `/health`; pydantic schema validation; JPEG magic-byte check; 5 MB cap; a re-upload never overwrites stored evidence; per-client rate limit. |
| Road authorities | Spam, false reports, duplicate tickets | Second-model verification; cross-class duplicate merging; sightings near a report a reviewer rejected are suppressed for 90 days; matches against the city's own open requests are shown before approval; **nothing is sent without a reviewer's approval**. |
| People's accounts | Credential stuffing, session theft, CSRF | scrypt password hashes, a password policy, per-IP and per-account sign-in throttling, HMAC-signed HttpOnly SameSite=Strict session cookies (Secure behind HTTPS), a CSRF token on every state change, OIDC single sign-on with ID-token signature, audience, issuer and nonce checks (`web/auth.py`). |
| LLM prompts | Personal data sent to third-party model providers | Agents get text metadata only through a field allow-list (`reports_server._for_agent`), never images, identities or delivery records. `ROADSENSE_DATA_RESIDENCY=ca` refuses any LLM host not on the allow-list and any free (prompt-logging) model. |

## Roles

| Role | Can |
|---|---|
| admin | everything, manage users, sync city data |
| reviewer | approve, reject, correct the damage class, resend, run follow-up, upload trips |
| driver | upload trips, see results |
| viewer | read only |

The web app checks the role, and the agent API checks it again from the forwarded identity headers (trusted only
with the service token), so a compromised browser session cannot approve without the reviewer role. Every
approval records who approved, and the audit log records every sign-in, user change and decision.

## OWASP Top 10 for Agentic Applications (2026) mapping

| Risk | Control in RoadSense |
|---|---|
| ASI01 Agent goal hijack | Tool results are declared data, not instructions, in every specialist prompt. Outputs that change state are enums or ids (`agents/contracts.py`); model-written text is length-capped and stripped of links and markup (`reports_server._clean_text`). |
| ASI02 Tool misuse | Each specialist gets only its own tools; the allow-list is enforced in the client loop. The triage tool accepts only an authority supported by the map evidence and uses the rule's severity; disagreements are logged (`severity_disagreement`, `jurisdiction_overridden`). |
| ASI03 Identity and privilege abuse | The only tool that reaches an authority takes a report id and nothing else; it sends the payload snapshot the reviewer approved and refuses if its hash no longer matches. |
| ASI08 Cascading failures | The deterministic fallback completes any step the agents skip. Jobs are durable and re-queued after a restart. Failed deliveries back off (1 min → 6 h) and stop after `ROADSENSE_MAX_DELIVERY_ATTEMPTS`, flagging the report for a manual resend. |
| ASI09 Human-agent trust exploitation | The reviewer sees the exact payload. Approval stores the payload and its SHA-256; delivery sends that snapshot. New evidence after approval is pushed to the authority as an update, never by changing what was approved. |
| ASI10 Rogue agents | Append-only audit log (SQLite triggers reject UPDATE and DELETE). `ROADSENSE_AGENTS_ENABLED=0` is a kill switch. |
| ASI04 Supply chain | Exact versions in `requirements.lock`; CI runs lint, tests and `pip-audit`. MCP servers run locally over stdio. Leaflet is vendored. |

## Web app

- The browser never holds the agent API token: the web server keeps it and forwards a fixed set of calls.
- Every `/api` call needs a session; changes also need the CSRF token.
- Security headers on every response: a Content-Security-Policy (self, OpenStreetMap tiles, Google Fonts),
  `X-Frame-Options: DENY`, `nosniff`, a strict referrer policy, and HSTS when `ROADSENSE_COOKIE_SECURE=1`.
- Everything rendered from the server, including agent-written text, is HTML-escaped.
- `/metrics` (Prometheus format) needs the service token on the agent API and an admin session on the web app.

## Model providers and data residency

The development defaults are free OpenRouter models, which may log prompts. Nova Scotia's PIIDPA bars public
bodies from storing or accessing personal information outside Canada, and the new FOIPOP Act (in force
2027-04-01) keeps a cross-border restriction. For a municipal deployment:

1. Point `OPENROUTER_BASE_URL` at a Canadian, no-retention OpenAI-compatible endpoint (a Canadian-region cloud
   deployment, or a self-hosted vLLM/Ollama server with a local model).
2. Set `ROADSENSE_DATA_RESIDENCY=ca` and list that host in `ROADSENSE_RESIDENCY_LLM_HOSTS`.
3. Host the application and its data volume in a Canadian region, and use a Canadian OSRM/Nominatim instance.

The Trust & system page lists every setting that is still a development default.

## Before a pilot

- A privacy impact assessment, and counsel review of PIIDPA / FOIPOP and PIPEDA obligations.
- An external penetration test of the deployed configuration.
- Breach-notification procedure (mandatory under the new FOIPOP Act).
- Driver distraction: the capture device must be touch-free while moving; review happens after the trip.
- Validation of the Cityworks / ArcGIS field mapping against the city's test instance.

## Reporting a vulnerability

Open a private security advisory on the repository or email the maintainers. Please do not test against real
municipal systems: the demo files only to the local mock Open311 server.
