# Demo trip

Six events with fixed ids (`trip/demo-01..06`), built by `scripts/build_demo_trip.py` from labelled RDD2022
test-split images (held-out roads; images © the RDD2022 authors, used for research/demo). Frames are redacted the
same way the edge device does it. Positions are placed on Halifax roads to exercise every agent decision; see
`trip/manifest.json`.

`llm_cache.json` (created by `python scripts/demo.py --record`) holds a real recorded run of the agents, so
`python scripts/demo.py` can replay it without an API key.
