"""``/v1/network/config`` — each user pointing Nira at their own network.

The address a phone is handed has to be one the phone can reach, and no
detector gets that right for everyone: a tailnet, a router with a reserved
lease, a hostname only the LAN resolves. These tests pin that the choice is
the user's, that it survives a restart, and that a mode which cannot be
satisfied is reported rather than silently replaced.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from nira.core.config import load_config
from nira.core.config_writer import read_config_document


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('[engine]\ndefault = "ollama"\n', encoding="utf-8")
    monkeypatch.setenv("NIRA_CONFIG", str(path))
    return path


@pytest.fixture
def client(config_file):
    from nira.server.app import create_app

    config = load_config()
    app = create_app(engine=None, model="test-model", config=config)
    app.state.config = config
    with TestClient(app) as test_client:
        yield test_client


def test_get_reports_the_candidates(client):
    body = client.get("/v1/network/config").json()
    assert body["mode"] == "auto"
    kinds = [c["kind"] for c in body["candidates"]]
    assert "loopback" in kinds, "the fallback must always be listed"
    assert body["current"] is not None


def test_loopback_is_labelled_unreachable(client):
    body = client.get("/v1/network/config").json()
    loopback = next(c for c in body["candidates"] if c["kind"] == "loopback")
    assert loopback["reachable_off_machine"] is False


def test_setting_a_host_persists_and_switches_to_manual(client, config_file):
    resp = client.put("/v1/network/config", json={"advertise_host": "nira.lan"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["mode"] == "manual", (
        "a host saved under mode 'auto' would be written and then ignored"
    )
    assert body["current"]["url"].startswith("http://nira.lan")

    doc = read_config_document(config_file)
    assert doc["network"]["advertise_host"] == "nira.lan"
    assert doc["network"]["mode"] == "manual"
    assert load_config().network.advertise_host == "nira.lan"


def test_manual_without_a_host_is_refused(client):
    resp = client.put("/v1/network/config", json={"mode": "manual"})
    assert resp.status_code == 422
    assert "advertise_host" in resp.json()["detail"]


def test_an_unsatisfiable_mode_is_reported_not_swapped(client, monkeypatch):
    from nira.server import advertise

    monkeypatch.setattr(advertise, "_tailnet_candidates", lambda timeout=5.0: [])
    resp = client.put("/v1/network/config", json={"mode": "tailscale"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["current"] is None
    assert "tailnet" in body["error"]
    assert body["mode"] == "tailscale", "the setting stands; the UI shows why"


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "carrier-pigeon"},
        {"advertise_scheme": "gopher"},
        {"advertise_port": 70000},
        {"advertise_port": -1},
    ],
)
def test_bad_values_are_rejected(client, payload):
    assert client.put("/v1/network/config", json=payload).status_code == 422


def test_an_empty_update_is_refused(client):
    assert client.put("/v1/network/config", json={}).status_code == 422


def test_explicit_mode_beats_the_host_implication(client, config_file):
    # Someone setting both means it: --host with --mode lan is a pinned
    # address they want ignored until they switch back.
    resp = client.put(
        "/v1/network/config", json={"advertise_host": "nira.lan", "mode": "auto"}
    )
    assert resp.status_code == 200
    assert read_config_document(config_file)["network"]["mode"] == "auto"


def test_settings_apply_without_a_restart(client):
    client.put("/v1/network/config", json={"advertise_host": "first.lan"})
    client.put("/v1/network/config", json={"advertise_host": "second.lan"})
    body = client.get("/v1/network/config").json()
    assert body["current"]["url"].startswith("http://second.lan")
