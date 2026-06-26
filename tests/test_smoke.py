def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.text == "ok"


def test_readyz_ok(client):
    r = client.get("/readyz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["alembic_version"]


def test_root(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "VoiceAgent" in r.text


def test_dashboard_login_form(client):
    r = client.get("/dashboard/login")
    assert r.status_code == 200
    assert "<form" in r.text


def test_dashboard_home_unauth(client):
    r = client.get("/dashboard/")
    assert r.status_code == 401


def test_zvonar_turn_unauth(client):
    r = client.post(
        "/zvonar/dialogue/turn",
        json={"lead_id": 1, "session_id": "s", "turn": 0, "user_speech": ""},
    )
    assert r.status_code == 401


def test_zvonar_turn_with_token(client):
    from shared.settings import get_settings

    token = get_settings().secret_key
    r = client.post(
        "/zvonar/dialogue/turn",
        json={"lead_id": 1, "session_id": "s", "turn": 0, "user_speech": ""},
        headers={"X-Token": token},
    )
    assert r.status_code == 200
    assert "Олимп" in r.json()["text"]


def test_webhook_smoke(client, session):
    from shared.models import ManagerCall

    payload = {
        "call_id": "test-1",
        "phone": "+77001234567",
        "direction": "inbound",
        "start": 1730000000,
        "duration": 30,
        "record_url": None,
    }
    r = client.post("/webhooks/onlinepbx", json=payload)
    assert r.status_code == 202
    assert r.json()["status"] == "accepted"
    assert session.query(ManagerCall).filter_by(onlinepbx_id="test-1").count() == 1
