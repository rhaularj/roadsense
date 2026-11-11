import asyncio
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from roadsense.agents.orchestrator import run_agent
from roadsense.services import agent_api
from roadsense.services.mock_open311 import create_app

AUTH = {"Authorization": "Bearer test-token"}
EVENT = {"id": "trip1-3-abc123", "trip_id": "trip1", "track_id": 3, "class_code": "D40", "class_name": "Pothole",
         "confidence": 0.71, "frames_seen": 4, "box": [10, 20, 110, 90], "box_area_ratio": 0.02, "lat": 44.643,
         "lon": -63.58, "heading": 90.0, "captured_at": "2026-11-02T12:00:00Z"}
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100


def test_open311_mock_contract(tmp_path):
    c = TestClient(create_app(tmp_path / "311.db"))
    form = {"service_code": "POTHOLE", "lat": 44.6, "long": -63.5, "description": "Pothole"}
    assert c.post("/requests.json", data={**form, "api_key": "wrong"}).status_code == 403
    rid = c.post("/requests.json", data={**form, "api_key": "test-key"}).json()[0]["service_request_id"]
    assert c.get(f"/requests/{rid}.json").json()[0]["status"] == "open"
    c.post(f"/admin/requests/{rid}/close", data={"notes": "Patched"})
    assert c.get(f"/requests/{rid}.json").json()[0]["status"] == "closed"


def test_event_upload_requires_token_and_valid_payload(db):
    c = TestClient(agent_api.app)  # no lifespan: the agent worker is not started
    files = {"image": ("e.jpg", JPEG, "image/jpeg")}
    assert c.post("/events", data={"event": json.dumps(EVENT)}, files=files).status_code == 401
    bad = {**EVENT, "class_code": "D99"}
    assert c.post("/events", data={"event": json.dumps(bad)}, files=files, headers=AUTH).status_code == 422
    not_jpeg = {"image": ("e.jpg", b"GIF89a", "image/jpeg")}
    assert c.post("/events", data={"event": json.dumps(EVENT)}, files=not_jpeg, headers=AUTH).status_code == 415
    assert c.post("/events", data={"event": json.dumps(EVENT)}, files=files, headers=AUTH).json() == {
        "accepted": EVENT["id"]}
    assert c.get("/trips/trip1/events").json()[0]["status"] == "received"


class StubLLM:
    """Scripted model: first asks for an allowed and a forbidden tool, then answers."""

    last_model = "stub"

    def __init__(self):
        self.turn = 0

    async def chat(self, messages, tools):
        self.turn += 1
        if self.turn == 1:
            call = lambda i, n: SimpleNamespace(id=i, function=SimpleNamespace(name=n, arguments='{"x": 1}'),
                                                model_dump=lambda: {"id": i, "type": "function",
                                                                    "function": {"name": n, "arguments": '{"x": 1}'}})
            return SimpleNamespace(content="", tool_calls=[call("a", "allowed"), call("b", "submit_service_request")])
        self.seen = [m for m in messages if m["role"] == "tool"]
        return SimpleNamespace(content='{"done": true}', tool_calls=None)


def test_agent_loop_enforces_tool_allow_list(db):
    llm, calls = StubLLM(), []

    async def call(name, args):
        calls.append(name)
        return {"ok": True}

    tools = [{"type": "function", "function": {"name": "allowed", "parameters": {"type": "object"}}}]
    answer = asyncio.run(run_agent(llm, "system", "task", tools, call, "agent:test"))
    assert answer == '{"done": true}'
    assert calls == ["allowed"]  # the forbidden tool never reached a server
    assert "not available" in llm.seen[1]["content"]
