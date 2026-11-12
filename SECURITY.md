# RoadSense security and privacy

RoadSense handles road imagery and location from drivers, runs LLM agents that call tools, and sends reports to
public authorities. This document lists the threats we design against and where each control lives in the code.
It is a student MVP: the controls are real and tested, but the system has not had an external security review.

## Threat model

| Asset | Threat | Control |
|---|---|---|
| Bystanders in dashcam frames | Faces, plates, house numbers leave the vehicle | Redaction **on the device** before upload: everything outside the damage box is blurred (`edge/redact.py`). JPEG re-encoded, no EXIF. Raw video never leaves the device. |
| Driver location history | Trips reconstructed from uploads | Only frames that contain damage are uploaded, never the track. Media ids carry a random suffix. |
| Report pipeline | Forged or malformed uploads | Bearer token, pydantic schema validation (class codes, coordinate ranges), JPEG magic-byte check, 5 MB cap (`services/agent_api.py`). Per-client rate limit (120 requests/min). |
| Road authorities | Spam or false reports | Second-model verification with a rule tuned on validation data; duplicate merging; **nothing is sent without the driver's approval**. |
| LLM prompts | Personal data sent to third-party model providers | Agents get text metadata only (ids, classes, confidences, coordinates of the defect), never images or driver identity. Free providers may retain prompts; see "Model providers". |

## OWASP Top 10 for Agentic Applications (2026) mapping

| Risk | Control in RoadSense |
|---|---|
| ASI01 Agent goal hijack | Tool results and any text inside them are declared data, not instructions, in every specialist prompt. Outputs that change state are enums or ids (`agents/contracts.py`); model-written text is length-capped and stripped of links and markup before storage (`reports_server._clean_text`). |
| ASI02 Tool misuse | Each specialist gets only its own tools; the allow-list is enforced in the client loop, not just the prompt (`orchestrator.run_agent`, tested in `test_agent_loop_enforces_tool_allow_list`). During trip processing the Filing agent gets drafting tools only. |
| ASI03 Identity and privilege abuse | The only tool that reaches an authority (`city_submit_request`) takes a report id and nothing else; it rebuilds the payload from the database and refuses unapproved reports. |
| ASI08 Cascading failures | The deterministic fallback acts as a circuit breaker: it completes any step the agents skip, every call is idempotent, and its use is reported as the fallback rate. LLM calls are budgeted per run and rate-limited. |
| ASI09 Human-agent trust exploitation | The driver sees the **exact payload** the authority will receive. Approval stores its SHA-256; submission refuses if the payload changed after approval (`test_payload_is_locked_after_approval`). Disputed classes and Priority 1 candidates are flagged on the review card. |
| ASI10 Rogue agents | Every plan, verdict, tool call and status change goes to an append-only audit log (SQLite triggers reject UPDATE and DELETE, `test_audit_log_is_append_only`). `ROADSENSE_AGENTS_ENABLED=0` is a kill switch that leaves only the deterministic pipeline. |
| ASI04 Supply chain | Dependencies are pinned in `requirements.txt`; `scripts/check.py` runs `pip-audit` when it is installed. MCP servers run locally over stdio, which is the smallest attack surface the MCP spec offers. |

## Dependencies

`scripts/check.py` runs `pip-audit` against `requirements.txt`: no known vulnerabilities (2026-11-03). Pillow is pinned
to `>=13.0.0`, which became possible when the Gradio dashboard was replaced by the RoadSense web app. The web app's
only front-end library, Leaflet 1.9.4, is vendored in the repo, so the UI loads no third-party scripts at runtime.

## Web app

- The browser never holds the agent API token: the web server keeps it and forwards a fixed set of calls.
- Everything rendered from the server, including agent-written rationales and drafts, is HTML-escaped before it is
  inserted into the page.
- Uploads are limited by type (video: mp4/mov/avi/mkv, up to 500 MB; GPS: gpx/csv) and processed one at a time.
- The app binds to localhost by default.

## Model providers

The default models are free OpenRouter models. Free endpoints may log prompts (one review reports 55-day retention
for Google AI Studio). That is why prompts contain no images, no driver identity and no track history. For a
municipal deployment, use a provider with a no-retention agreement hosted in Canada: Nova Scotia's PIIDPA
restricts storing or accessing public bodies' personal information outside Canada.

## Privacy law notes (not legal advice)

- **PIPEDA** applies once RoadSense pools drivers' frames commercially. The defensible position is data
  minimisation and redaction before upload, which the edge pipeline does by design.
- **Selling to a municipality** brings PIIDPA: host in a Canadian cloud region and keep support access in Canada.
- **Driver distraction:** the app must be mounted and touch-free while moving. Approval happens in the end-of-trip
  review, never while driving.
- A privacy impact assessment and counsel review are needed before any pilot with real drivers.

## Reporting a vulnerability

Open a private issue or email the maintainers. Please do not test against real municipal 311 systems: the demo
files only to the local mock Open311 server.
