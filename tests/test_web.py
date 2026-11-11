from fastapi.testclient import TestClient

from roadsense.common.config import settings
from roadsense.web.app import app

client = TestClient(app)


def test_serves_the_single_page_app_for_any_route():
    for path in ("/", "/review", "/anything/else"):
        r = client.get(path)
        assert r.status_code == 200 and "<title>RoadSense</title>" in r.text


def test_browser_assets_never_contain_the_api_token():
    for path in ("/", "/static/app.js", "/static/app.css"):
        assert settings.api_token not in client.get(path).text


def test_agent_text_is_escaped_before_rendering():
    js = client.get("/static/app.js").text
    assert "const esc = " in js and "esc(why)" in js and "esc(p.description)" in js


def test_media_rejects_path_tricks():
    assert client.get("/api/media/..%2F..%2Fsecret.jpg").status_code in (400, 404)
    assert client.get("/api/media/bad$id.jpg").status_code == 400


def test_upload_rejects_non_video():
    r = client.post("/api/trips", files={"video": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415


def test_sending_a_report_is_never_a_single_keystroke():
    js = client.get("/static/app.js").text
    assert '$("#approve")?.click()' not in js and '$("#reject")?.click()' not in js


def test_render_functions_do_not_shadow_stage():
    import re

    js = client.get("/static/app.js").text
    # stage() hands each render its container; a local `const stage` inside a render breaks that page
    assert len(re.findall(r"const stage\s*=", js)) == 1
