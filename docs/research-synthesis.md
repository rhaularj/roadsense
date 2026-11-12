## Research Synthesis: RoadSense users, stakeholders and UI needs
**Method:** Desk research (secondary sources) synthesised from five research briefs, plus the team's own measured
results | **Participants:** none interviewed yet (see Methodology Notes)
**Date:** 2026-11-02 to 2026-11-03 | **Researcher:** RoadSense team, with AI-assisted research

### Executive Summary
Nobody in the market owns the "last mile" of road-damage reporting: turning a detection into one accepted,
non-duplicate, correctly routed 311 ticket that someone follows up. Halifax's own 2026 numbers show the pain: 3,203
pothole reports in 11 weeks, which the city says include duplicates and potholes on provincial roads it does not
maintain. Three audiences meet in the product: drivers want zero effort and proof their report counted; city
staff want fewer, better, deduplicated tickets they can trust; judges want to see the agents make visible decisions
under human control. The UI has to make the agents' judgement legible and keep a human in charge of every report
that leaves the system.

### Key Themes

#### Theme 1: The pain is duplicate and misrouted reports, not detection
**Evidence strength:** Strong (municipal statement, news, 5 of 5 research briefs touch it)
**Summary:** Cities already receive thousands of reports. The cost is triage: the same pothole reported many times,
and provincial-road potholes landing in the municipal queue.
**Supporting Evidence:**
- "could include the same pothole being reported multiple times" — HRM, via CityNews (2026)
- HRM counts include provincial roads; provincial potholes go to a separate channel (NS Public Works) — CityNews,
  Port Hawkesbury Reporter
- Waymo's pothole feed to cities sends "location only", and Austin says it won't replace 311 — Waymo blog (2026)
- Measured: on 42 scenarios our agents routed 100% correctly and merged 100% of second sightings
**Implication:** The UI should lead with "duplicates avoided" and "routed to the right authority", not detection
boxes. The merge and the routing decision must be visible on every report.

#### Theme 2: Trust comes from evidence, not from the model's accuracy number
**Evidence strength:** Strong (judging research, OWASP agentic guidance, our own eval)
**Summary:** A 0.59 F1 detector sounds weak. It becomes credible when every report shows its evidence chain: two
models agreed, at what confidence, why it was routed where, and that a human approved the exact text.
**Supporting Evidence:**
- Judges probe "won't you flood city crews with false reports?" — judging brief, likely Q1
- OWASP ASI09 (human-agent trust): show users exactly what will be executed — OWASP Agentic Top 10 (2025)
- Agents already write rationales: "RT-DETR-L confirms D00 at confidence 0.90 with IoU 0.89, class agrees"
- Measured: verification lifts precision 0.714 → 0.744 and removes 21% of false alarms (modest, honest)
**Implication:** Each report card needs an evidence timeline (edge → verifier → location → triage → draft) and the
exact payload. Uncertainty (class disputed, position ±m) is a feature to show, not to hide.

#### Theme 3: The driver must never be asked to act while driving
**Evidence strength:** Strong (Nova Scotia Traffic Safety Act, privacy brief)
**Summary:** Nova Scotia's new Traffic Safety Act tightens hand-held device use. Any prompt while moving is a
liability.
**Supporting Evidence:**
- Product rules: "no notifications or prompts while the vehicle is moving", approval at a stop or after the trip —
  privacy brief
- Fleets (transit, waste trucks) avoid citizen distraction entirely and are the safer first channel — privacy brief
**Implication:** The driver experience is an end-of-trip review inbox ("5 defects found, review"), batched, with
one-tap approve. Fleet operators need the same inbox at scale.

#### Theme 4: Drivers need a reason to participate
**Evidence strength:** Medium (claims rules, CAA cost data; no driver interviews yet)
**Summary:** Calling 311 is effort with no feedback. Drivers gain from a "notice receipt" and closed-loop updates.
**Supporting Evidence:**
- Nova Scotia claims require prior notice to the province plus an expired service standard; fewer than 8% are paid
  — CBC, Global News
- Poor roads cost Canadian drivers $3B a year, about $126 each — CAA (2021)
- Damage per incident $50–$1,000 — CTV Atlantic
**Implication:** Show each driver their reports, the timestamped receipt (request id, date), and "fixed" status with
a notification. "Your report started the repair clock" is the hook.

#### Theme 5: Cities buy outcomes, privacy and residency, not AI
**Evidence strength:** Medium (procurement records, PIIDPA, vendor pricing)
**Summary:** Comparable products sell to road owners at $4.3k–$47k a year. Public bodies in Nova Scotia must keep
personal information in Canada (PIIDPA).
**Supporting Evidence:**
- Contracts up to $100k can be exempt from HRM procurement policy; FCM asset-management grants cover up to 80% to
  $50k — privacy/business brief
- On-device redaction: only the damage leaves the vehicle — our implementation
**Implication:** A city-facing view should speak in operations metrics (open requests, priority queue, Priority 1
candidates, repairs confirmed) and display privacy guarantees plainly.

#### Theme 6: Judges reward one memorable, visible agent moment
**Evidence strength:** Medium (judging guides, Cognizant's own messaging)
**Summary:** Winners show a single "this is now possible" moment, with the agent trace on screen, plus before/after
numbers in Cognizant's style ("four weeks to four minutes").
**Supporting Evidence:**
- The distinctive moments: an agent declining to file a duplicate, or confirming a fix — judging brief
- Cognizant Agent Foundry stresses "observability, governance, FinOps" — Cognizant
**Implication:** Make the agent trace a first-class screen, show cost per trip (LLM calls, tokens), and a live
before/after strip: "36 detections → 30 reports → 0 duplicates filed".

### Insights → Opportunities

| Insight | Opportunity | Impact | Effort |
|---------|-------------|--------|--------|
| Duplicates and misrouting are the city's pain | Overview KPIs for duplicates merged and authority routing; merge badge on each report | High | Low |
| Trust needs a visible evidence chain | Report detail with an agent decision timeline and the exact hash-locked payload | High | Med |
| No action while driving | End-of-trip review inbox with batch approve; nothing actionable during a drive | High | Low |
| Drivers want proof and closure | "My reports" with receipts, status pills and fixed notifications | Med | Low |
| Cities buy operations outcomes | City view: priority queue, Priority 1 candidates, request status | Med | Med |
| Judges reward visible agency and governance | Live agent activity feed, cost per trip, guardrail status panel | High | Med |
| Uncertainty is real (F1 0.59, ±m position) | Show confidence, "class disputed", position uncertainty as calm UI, not alarms | Med | Low |

### User Segments Identified
| Segment | Characteristics | Needs | Size |
|---------|----------------|-------|------|
| Commuter driver | Phone or dashcam, drives the same routes, low patience for forms | Zero effort, after-trip review, proof and closure | Largest by count |
| Fleet operator | Transit, waste, delivery vehicles covering many km daily | Coverage, batch approval, no driver distraction | Few, high volume (best first channel) |
| City operations staff | 311 / public works dispatchers | Fewer, verified, deduplicated, prioritised tickets in their own channel | Few per city |
| Provincial road authority | NS Public Works, 100-series highways | Correctly routed referrals with evidence | One per province |
| Judges / evaluators | Cognizant leaders, technical and business | See agentic decisions, governance, measured impact quickly | Panel |

### Recommendations
1. **[High priority] Replace the demo-style dashboard with a product-grade web app** organised around the review
   inbox and the evidence chain. Themes 1, 2, 3.
2. **[High priority] Make agent decisions first-class UI**: a decision timeline per report and an activity feed per
   trip, with cost and guardrail status. Themes 2, 6.
3. **[Medium priority] Lead the overview with outcome metrics**: duplicates merged, routed to province, false alarms
   removed, Priority 1 candidates, repairs confirmed. Themes 1, 5.
4. **[Medium priority] Driver closure**: receipts, status and fixed notifications on every report. Theme 4.
5. **[Lower priority] Separate city workspace** with its own login and queue (post-hackathon). Theme 5.

### Questions for Further Research
- Do Halifax drivers actually want to review reports after a trip, or would they rather auto-send above a threshold?
- How do HRM 311 dispatchers triage today, and what would make them accept third-party reports?
- What share of HRM's 3,203 reports were duplicates or provincial? (No published figure.)
- Is "notice receipt" a strong enough incentive, or do fleets need a paid model?
- How long does a driver tolerate the end-of-trip review: 5 items? 30?

### Methodology Notes
This synthesis draws on secondary research only: five briefs covering market and Halifax context, computer vision,
agentic AI practice, privacy and business, and hackathon judging (about 20,000 words, with source URLs), plus the
team's measured evaluations. No drivers, dispatchers or judges were interviewed, so "evidence strength" replaces
participant counts. Several Halifax figures come via a news aggregator and should be checked against the original
CityNews reporting. Recommended next step: five 20-minute interviews (two drivers, one fleet operator, one HRM 311
or public works staff member, one Dalhousie/ShiftKey mentor) and a usability test of the review inbox before Nov 15.
