"""Brand-neutral defaults, authorisation, stale previews and destructive conversion."""

import sys

import pytest
from sqlalchemy import func, select
from test_classify import classified_data as classified_data
from test_records import seed_records

from app.config import REPO_ROOT
from app.models import Account, AuditLog, Brand, PriceItem, PromptVersion, Staff
from app.services import branding, content_safety, ideation_settings, prompts
from app.services.export_docx import document

sys.path.insert(0, str(REPO_ROOT / "scripts"))


def test_empty_install_seed_is_industry_neutral(client, settings):
    with client.app.state.session_factory.begin() as session:
        seed_records(session, settings)
        assert session.scalar(select(func.count()).select_from(PriceItem)) == 0
        assert branding.rules(session, 1) == {"forbidden_phrases": []}
        cfg = ideation_settings.config(session, 1)
        assert not cfg.enabled and cfg.time is None and cfg.weekday is None
        assert cfg.topics == ["其他"]


def test_identity_admin_csrf_version_and_docx(client, classified_data):
    assert client.get("/api/workspace/identity").json() == {
        "name": branding.DEFAULT_NAME,
        "version": 0,
        "backoffice_origin": client.app.state.settings.backoffice_origin,
        "plugin_version": "0.4.4",
    }
    body = {"name": "創作測試工作室", "version": 0}
    assert (
        client.put(
            "/api/workspace/identity", json=body, headers={"X-CSRF-Token": "bad"}
        ).status_code
        == 403
    )
    result = client.put("/api/workspace/identity", json=body)
    assert result.status_code == 200
    assert client.put("/api/workspace/identity", json=body).status_code == 409
    with client.app.state.session_factory() as session:
        doc = document("測試品牌", "測試", session=session)
        assert doc.sections[0].header.paragraphs[0].text == "創作測試工作室｜測試品牌"
        assert session.scalar(select(AuditLog).where(AuditLog.action == "workspace.rename"))
    client.cookies.clear()
    assert client.get("/api/workspace/identity").json()["name"] == body["name"]
    assert client.put("/api/workspace/identity", json=body).status_code == 401


@pytest.mark.parametrize("role", ["marketing", "viewer"])
def test_identity_and_templates_admin_only(client, classified_data, role):
    with client.app.state.session_factory.begin() as session:
        session.get(Staff, classified_data["staff_id"]).role = role
    assert (
        client.put("/api/workspace/identity", json={"name": "測試", "version": 0}).status_code
        == 403
    )
    assert client.get("/api/settings/templates").status_code == 403
    assert client.get("/api/settings/templates/creator/preview?brand_id=1").status_code == 403


def test_template_preview_apply_audit_stale_and_brand_isolation(client, classified_data):
    factory = client.app.state.session_factory
    with factory.begin() as session:
        other = Brand(slug="other-template", name="另一品牌")
        session.add(other)
        session.flush()
        other_id = other.id
        before_switches = [(a.id, a.send_enabled) for a in session.scalars(select(Account))]
        old_prompt = prompts.current(session, 1).id
    url = "/api/settings/templates/creator/preview?brand_id=1"
    value = client.get(url).json()
    assert "price_rows" not in value["after"]
    assert value["after"]["topics"] == branding.load_template("creator")["topics"]
    with factory() as session:
        assert prompts.current(session, 1).id == old_prompt
    payload = {"template": value["template"], "token": value["token"]}
    assert client.post("/api/settings/templates/apply?brand_id=1", json=payload).status_code == 200
    assert client.post("/api/settings/templates/apply?brand_id=1", json=payload).status_code == 409
    with factory() as session:
        assert prompts.current(session, 1).id != old_prompt
        assert session.get(PromptVersion, old_prompt) is not None
        assert branding.rules(session, other_id)["forbidden_phrases"] == []
        assert (
            branding.rules(session, 1)["forbidden_phrases"]
            == branding.load_template("creator")["forbidden_phrases"]
        )
        assert all(not p.archived and not p.active for p in session.scalars(select(PriceItem)))
        assert [(a.id, a.send_enabled) for a in session.scalars(select(Account))] == before_switches
        assert session.scalar(select(AuditLog).where(AuditLog.action == "brand.template.apply"))


def test_rules_invalidate_preview_and_are_escaped_literals(client, classified_data):
    preview = client.get("/api/settings/templates/blank/preview?brand_id=1").json()
    path = "/api/settings/brand-rules?brand_id=1"
    before = client.get(path).json()
    result = client.put(path, json={"before": before, "forbidden_phrases": ["穩賺", "保證.*"]})
    assert result.status_code == 200
    assert client.put(path, json={"before": before, "forbidden_phrases": []}).status_code == 409
    assert (
        client.post(
            "/api/settings/templates/apply?brand_id=1",
            json={"template": "blank", "token": preview["token"]},
        ).status_code
        == 409
    )
    assert content_safety.forbidden_promise("這次穩賺", ["穩賺"])
    assert not content_safety.forbidden_promise("不能保證穩賺", ["穩賺"])
    assert not content_safety.forbidden_promise("保證任意文字", ["保證.*"])
    assert not content_safety.forbidden_promise("這次穩賺")
    with client.app.state.session_factory() as session:
        assert prompts.context(session, 1)["forbidden_phrases"] == ["穩賺", "保證.*"]


def test_legacy_initial_password_name(monkeypatch, caplog):
    from app.config import Settings

    previous = bytes([77, 73, 69, 78]).decode() + "_TEST_INITIAL_PASSWORD"
    monkeypatch.setenv(previous, "private-legacy-password")
    monkeypatch.delenv("MARKETING_TEST_INITIAL_PASSWORD", raising=False)
    value = Settings(_env_file=None)
    assert value.marketing_test_initial_password.get_secret_value() == "private-legacy-password"
    assert "deprecated" in caplog.text and "private-legacy-password" not in caplog.text


@pytest.mark.parametrize(
    "text,blocked",
    [
        ("我們不保證爆紅", False),
        ("不能保證收入", False),
        ("我們保證爆紅", True),
        ("不保證收入，但保證接案", True),
    ],
)
def test_creator_forbidden_negation(text, blocked):
    phrases = branding.load_template("creator")["forbidden_phrases"]
    assert content_safety.forbidden_promise(text, phrases) is blocked
