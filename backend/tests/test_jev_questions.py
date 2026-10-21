import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import runtime_tmp as runtime
from eval_jev_questions import cases, evaluate, main, matches, mock_post, request_for

from app.services import classify, content_safety, csv_import, ideation_evidence, jev, video_scripts

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def evaluation_output(monkeypatch):
    with runtime.runtime_tmp("jev-test") as folder:
        # Each worker owns its output root; imported script entry points must
        # never clear another worker's latest-output directory.
        monkeypatch.setattr(runtime, "RUNTIME", folder)
        yield folder / "result.json"


def resolve_path(state, path):
    for token in re.findall(r"[^.\[\]]+", path):
        state = state[int(token)] if isinstance(state, list) else state[token]
    return state


@pytest.mark.parametrize("case", cases(), ids=lambda c: c["id"])
def test_all_question_paths_exist(case):
    state, questions = request_for(case, "new")
    assert questions.keys() == case["expected"].keys()
    for question in questions.values():
        paths = re.findall(r"`([^`]+)`", json.dumps(question, ensure_ascii=False))
        assert paths, question
        for path in paths:
            resolve_path(state, path)
        assert question["instructions"]
        if question["type"] in {"choice", "score"}:
            assert all(question["criteria"])


def test_structural_checker_rejects_missing_and_handles_nested_array():
    assert (
        resolve_path({"ticket": {"messages": [{"text": "synthetic"}]}}, "ticket.messages[0].text")
        == "synthetic"
    )
    with pytest.raises(KeyError):
        resolve_path({"draft": ""}, "price_rows")


def test_request_builders_keep_roles_and_candidate_coverage():
    state = classify.question_state("客人問題", {"message": "wrong", "sender": "wrong"})
    assert state["message"] == "客人問題" and state["sender"] == "客人"
    assert video_scripts.CHECKS["forbidden_promise"] is content_safety.FORBIDDEN_PROMISE_CHECK
    assert "其他" in ideation_evidence.questions(["使用"])["topic"]["criteria"]
    state, questions = csv_import.mapping_request(
        {"2": {"header": "欄名", "samples": []}, "7": {"header": "另欄", "samples": []}}
    )
    assert set(questions) == {"2", "7"}
    for question in questions.values():
        resolve_path(state, re.findall(r"`([^`]+)`", question["instructions"])[0])


@pytest.mark.parametrize("choices,expected,calls", [(["none"], [], 1), (["1", "none"], [1], 2)])
def test_representatives_stop_at_none_without_fallback(monkeypatch, choices, expected, calls):
    mock = Mock(
        side_effect=[jev.Result({"answers": {"representative": {"choice": c}}}, 0) for c in choices]
    )
    monkeypatch.setattr(ideation_evidence, "judge", mock)
    pool = [{"id": i, "text": str(i), "pain": 1, "is_question": True} for i in (1, 2)]
    selected, method = ideation_evidence.representatives(None, None, 1, "使用", pool, "manual")
    assert [p["id"] for p in selected] == expected and method == "jev"
    assert mock.call_count == calls
    for call in mock.call_args_list:
        state, questions = call.args[4:6]
        assert set(questions["representative"]["criteria"]) == {
            *[str(p["id"]) for p in state["candidates"]],
            "none",
        }
    if calls == 2:
        assert mock.call_args_list[1].args[4]["already_selected"] == ["1"]


def test_wording_update_keeps_existing_hashes_valid():
    # 這次只調整措辭與寄件者標示：既有分流與主題結果維持有效，不觸發重算。
    old = hashlib.sha256(
        json.dumps(["text", {}, "triage-2026-09-26-v3"], ensure_ascii=False).encode()
    ).hexdigest()
    assert classify.fingerprint("text", {}) == old
    assert classify.QUESTION_VERSION != classify.FINGERPRINT_VERSION
    old_topic = hashlib.sha256(
        json.dumps(["text", ["使用"], "topic-v1"], ensure_ascii=False).encode()
    ).hexdigest()
    assert ideation_evidence.fingerprint(SimpleNamespace(text="text"), ["使用"]) == old_topic


@pytest.mark.parametrize("variant,request_count", [("both", 96), ("old", 48)])
def test_evaluator_offline_contract_and_mismatch_reporting(
    monkeypatch, evaluation_output, capsys, variant, request_count
):
    monkeypatch.setattr(jev, "post_json", lambda *a: pytest.fail("network transport reached"))
    monkeypatch.setattr(
        "app.config.Settings", lambda *a, **kw: pytest.fail("settings read offline")
    )
    from eval_jev_questions import ROOT

    output = evaluation_output
    assert main(["--variant", variant, "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["mode"] == "offline-double" and not report["quality_evidence"]
    assert report["request_count"] == request_count and report["errors"] == 0
    assert report["cases_per_group"]["classify"] == 16
    assert {count for group, count in report["cases_per_group"].items() if group != "classify"} == {
        8
    }
    assert any(not row["matches"] for row in report["rows"])
    assert all(
        ("comparison" in summary) == (variant == "both")
        for summary in report["summary"].values()
    )
    assert {row["variant"] for row in report["rows"]} == (
        {"old", "new"} if variant == "both" else {"old"}
    )
    assert "offline-double" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        main(["--output", str(ROOT / "outside-runtime.json")])


def test_evaluator_old_choices_and_failures(monkeypatch):
    case = next(c for c in cases() if c["group"] == "representative")
    old_state, old_questions = request_for(case, "old")
    assert "none" not in old_questions["representative"]["criteria"]
    _, response, _ = mock_post("", "", {"questions": old_questions}, 1)
    assert jev.valid_response(response, old_questions)
    assert old_state == case["state"]
    assert matches({"type": "noul", "noul": 0.9}, True)
    assert not matches({"type": "score", "score": 4}, [0, 1])
    monkeypatch.setattr(jev, "ask", lambda *a: jev.Result(None, 0, "invalid_response"))
    result = evaluate([case], ["old", "new"], None)
    assert result["errors"] == 2 and not any(r["matches"] for r in result["rows"])


def test_old_dynamic_criteria_do_not_depend_on_new_question_definitions():
    for group in ("representative",):
        case = next(c for c in cases() if c["group"] == group)
        _, original = request_for(case, "old")
        changed = {**case, "questions": {"unrelated": {"criteria": {"changed": "changed"}}}}
        assert request_for(changed, "old")[1] == original


def test_live_option_uses_isolated_settings_with_mock_transport(
    monkeypatch, evaluation_output, capsys
):
    from eval_jev_questions import ROOT

    from app.config import Settings

    observed = []

    def configured(**kwargs):
        assert all(path.is_relative_to(ROOT / ".runtime") for path in kwargs.values())
        assert not kwargs["database_path"].exists()
        return Settings(_env_file=None, jev_api_key="synthetic-key", **kwargs)

    def ask(state, questions, settings):
        assert not settings.database_path.exists()
        observed.append(questions)
        _, response, _ = mock_post("", "", {"questions": questions}, 1)
        return jev.Result(response, 0)

    monkeypatch.setattr("app.config.Settings", configured)
    monkeypatch.setattr(jev, "ask", ask)
    output = evaluation_output
    assert main(["--live", "--group", "csv", "--variant", "new", "--output", str(output)]) == 0
    assert len(observed) == 8
    assert "synthetic-key" not in capsys.readouterr().out
    monkeypatch.setattr("app.config.Settings", lambda **kw: SimpleNamespace(jev_api_key=None))
    with pytest.raises(SystemExit):
        main(["--live", "--output", str(output)])
    assert len(observed) == 8
