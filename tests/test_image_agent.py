"""Tests for ImageAgent (Phase C) — vision self-critique loop."""
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from pipeline.agents.image_agent import (
    ImageAgent,
    ImageAgentResult,
    _critique_image_with_vision,
    _refine_prompt,
    _flux_schnell,
    _flux_pro_with_ref,
)


# ─── Critique scoring tests ───────────────────────────────────────────────────


CRITIQUE_PASS = {
    "anatomy": 9,
    "domain_match": 9,
    "no_split_screen": 10,
    "equipment_match": 8,
    "composition": 9,
    "main_issue": None,
    "retry_hint": None,
}

CRITIQUE_FAIL_ANATOMY = {
    "anatomy": 3,
    "domain_match": 8,
    "no_split_screen": 10,
    "equipment_match": 7,
    "composition": 5,
    "main_issue": "Person has no neck, jacket appears floating",
    "retry_hint": "anatomically correct, complete person",
}


def _make_fake_image(tmp_path: Path) -> Path:
    """Create a fake PNG file."""
    img = tmp_path / "test.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200)
    return img


def test_critique_with_vision_returns_passed_for_good_image(tmp_path):
    img = _make_fake_image(tmp_path)
    fake_response = MagicMock()
    fake_response.text = json.dumps(CRITIQUE_PASS)

    with patch("pipeline.agents.image_agent.gemini_client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = fake_response
        mock_client_factory.return_value = mock_client

        result = _critique_image_with_vision(
            img,
            image_prompt="lab researcher",
            act="hook",
            equipment_type="laser",
            domain="lab",
        )

    assert result.passed
    assert result.score >= 7.0


def test_critique_with_vision_fails_for_broken_anatomy(tmp_path):
    img = _make_fake_image(tmp_path)
    fake_response = MagicMock()
    fake_response.text = json.dumps(CRITIQUE_FAIL_ANATOMY)

    with patch("pipeline.agents.image_agent.gemini_client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = fake_response
        mock_client_factory.return_value = mock_client

        result = _critique_image_with_vision(
            img,
            image_prompt="lab researcher",
            act="hook",
            equipment_type="laser",
            domain="lab",
        )

    assert not result.passed
    # main_issue should be in issues list
    assert any("neck" in issue.lower() for issue in result.issues)


def test_critique_fails_closed_on_gemini_error(tmp_path, monkeypatch):
    """If Gemini errors, critique fails closed (don't ship unreviewed images).

    This is a regression guard for an earlier fail-open behavior that silently
    accepted any image when the vision evaluator was down — defeating the
    purpose of the self-critique loop under degraded dependencies.
    """
    monkeypatch.delenv("ALLOW_CRITIQUE_FALLBACK", raising=False)
    img = _make_fake_image(tmp_path)

    with patch("pipeline.agents.image_agent.gemini_client") as mock_client_factory:
        mock_client_factory.side_effect = RuntimeError("Gemini down")
        result = _critique_image_with_vision(
            img,
            image_prompt="x",
            act="hook",
            equipment_type="x",
            domain="lab",
        )
    assert not result.passed
    assert result.score == 0.0
    assert any("critique unavailable" in i for i in result.issues)


def test_critique_fails_open_when_fallback_env_set(tmp_path, monkeypatch):
    """ALLOW_CRITIQUE_FALLBACK=1 reverts to fail-open for emergencies."""
    monkeypatch.setenv("ALLOW_CRITIQUE_FALLBACK", "1")
    img = _make_fake_image(tmp_path)

    with patch("pipeline.agents.image_agent.gemini_client") as mock_client_factory:
        mock_client_factory.side_effect = RuntimeError("Gemini down")
        result = _critique_image_with_vision(
            img,
            image_prompt="x", act="hook", equipment_type="x", domain="lab",
        )
    assert result.passed
    assert result.score >= 7.0
    assert any("fallback" in i for i in result.issues)


def test_critique_returns_zero_when_image_unreadable(tmp_path):
    nonexistent = tmp_path / "missing.png"
    result = _critique_image_with_vision(
        nonexistent,
        image_prompt="x", act="hook", equipment_type="x", domain="lab",
    )
    assert not result.passed
    assert result.score == 0.0


# ─── Prompt refinement ────────────────────────────────────────────────────────


def test_refine_prompt_returns_refined_text():
    fake_response = json.dumps({
        "refined_prompt": "Lab researcher in white coat, anatomically correct, single continuous shot",
        "what_changed": "Added anatomical correctness keyword",
    })
    with patch("pipeline.agents.image_agent.call_gemini_with_retry", return_value=fake_response):
        refined = _refine_prompt("Lab researcher", ["Person has no neck"])
    assert "anatomically" in refined or len(refined) > 20


def test_refine_prompt_keeps_original_on_no_issues():
    refined = _refine_prompt("Lab researcher in white coat", [])
    assert refined == "Lab researcher in white coat"


def test_refine_prompt_keeps_original_on_gemini_error():
    with patch("pipeline.agents.image_agent.call_gemini_with_retry", side_effect=RuntimeError("error")):
        refined = _refine_prompt("Lab researcher", ["bad anatomy"])
    assert refined == "Lab researcher"


# ─── Generation backend tests ─────────────────────────────────────────────────


def test_flux_schnell_writes_png(tmp_path):
    out = tmp_path / "out.png"
    fake = MagicMock()
    fake.read.return_value = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    with patch("pipeline.agents.image_agent.replicate.run") as mock_run:
        mock_run.return_value = [fake]
        success = _flux_schnell("test prompt", out)
    assert success
    assert out.exists()


def test_flux_pro_with_ref_writes_png(tmp_path):
    ref = _make_fake_image(tmp_path)
    out = tmp_path / "out.png"
    fake = MagicMock()
    fake.read.return_value = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
    # flux-1.1-pro returns single FileOutput
    with patch("pipeline.agents.image_agent.replicate.run") as mock_run:
        mock_run.return_value = fake
        success = _flux_pro_with_ref("test prompt", ref, out)
    assert success
    assert out.exists()


def test_flux_schnell_returns_false_on_persistent_error(tmp_path):
    out = tmp_path / "out.png"
    with patch("pipeline.agents.image_agent.replicate.run", side_effect=RuntimeError("API down")):
        success = _flux_schnell("test", out)
    assert not success


# ─── Full ImageAgent loop ─────────────────────────────────────────────────────


def test_image_agent_passes_on_first_attempt(tmp_path):
    """If critique passes immediately, no refine."""
    ref = _make_fake_image(tmp_path)
    out = tmp_path / "out.png"
    fake = MagicMock()
    fake.read.return_value = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
    fake_response = MagicMock()
    fake_response.text = json.dumps(CRITIQUE_PASS)

    scene = {"scene_id": "S01", "act": "hook", "image_prompt": "lab"}

    with patch("pipeline.agents.image_agent.replicate.run", return_value=fake), \
         patch("pipeline.agents.image_agent.gemini_client") as mc:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = fake_response
        mc.return_value = mock_client
        agent = ImageAgent(scene, equipment_type="laser", domain="lab", ref_path=ref)
        result = agent.run(out)

    assert result.success
    assert result.passed
    assert result.attempts == 1
    assert out.exists()
    # Attempt-specific files must not leak into the workspace
    assert not (tmp_path / "out.attempt1.png").exists()


def test_image_agent_refines_on_low_score(tmp_path):
    """If first critique fails, agent refines and retries."""
    ref = _make_fake_image(tmp_path)
    out = tmp_path / "out.png"
    fake = MagicMock()
    fake.read.return_value = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200

    # First critique fails (anatomy), second passes
    responses = [
        MagicMock(text=json.dumps(CRITIQUE_FAIL_ANATOMY)),
        MagicMock(text=json.dumps(CRITIQUE_PASS)),
    ]
    idx = {"i": 0}
    def _gemini_call(*args, **kwargs):
        i = idx["i"]
        idx["i"] += 1
        return responses[min(i, len(responses) - 1)]

    refine_response = json.dumps({
        "refined_prompt": "Lab researcher, anatomically correct, single continuous shot",
        "what_changed": "added anatomy keyword",
    })

    scene = {"scene_id": "S01", "act": "hook", "image_prompt": "lab"}

    with patch("pipeline.agents.image_agent.replicate.run", return_value=fake), \
         patch("pipeline.agents.image_agent.gemini_client") as mc, \
         patch("pipeline.agents.image_agent.call_gemini_with_retry", return_value=refine_response):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = _gemini_call
        mc.return_value = mock_client
        agent = ImageAgent(scene, equipment_type="laser", domain="lab", ref_path=ref, max_attempts=2)
        result = agent.run(out)

    assert result.attempts == 2
    assert result.success  # second attempt passes
    assert result.passed


def test_image_agent_returns_best_after_all_fail(tmp_path):
    """If all attempts fail critique, return the best one."""
    ref = _make_fake_image(tmp_path)
    out = tmp_path / "out.png"
    fake = MagicMock()
    fake.read.return_value = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
    fake_response = MagicMock()
    fake_response.text = json.dumps(CRITIQUE_FAIL_ANATOMY)
    refine_response = json.dumps({"refined_prompt": "different prompt with anatomy fix", "what_changed": "x"})

    scene = {"scene_id": "S01", "act": "hook", "image_prompt": "lab"}

    with patch("pipeline.agents.image_agent.replicate.run", return_value=fake) as mock_replicate, \
         patch("pipeline.agents.image_agent.gemini_client") as mc, \
         patch("pipeline.agents.image_agent.call_gemini_with_retry", return_value=refine_response):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = fake_response
        mc.return_value = mock_client
        agent = ImageAgent(scene, equipment_type="laser", domain="lab", ref_path=ref, max_attempts=2)
        result = agent.run(out)

    # Two attempts must have been made (replicate called twice)
    assert mock_replicate.call_count == 2
    # Score below threshold
    assert result.score < 7.0
    # Quality gate must report not-passed so callers can skip the scene
    assert not result.passed
    # File still exists (best of attempts) so downstream stages have something
    assert out.exists()
    # Attempt-specific files must be cleaned up
    assert not (tmp_path / "out.attempt1.png").exists()
    assert not (tmp_path / "out.attempt2.png").exists()


def test_image_agent_falls_back_to_schnell_on_ref_failure(tmp_path):
    """If flux-pro fails with reference, fall back to schnell."""
    ref = _make_fake_image(tmp_path)
    out = tmp_path / "out.png"
    fake = MagicMock()
    fake.read.return_value = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
    fake_response = MagicMock()
    fake_response.text = json.dumps(CRITIQUE_PASS)

    scene = {"scene_id": "S01", "act": "hook", "image_prompt": "lab"}

    # flux-pro fails (no read attr, IndexError), then schnell works
    bad_output = MagicMock()
    bad_output.read.side_effect = ValueError("empty")

    call_count = {"i": 0}
    def _replicate(model, **kwargs):
        call_count["i"] += 1
        if call_count["i"] == 1:
            # First call (flux-pro with ref) fails persistently
            raise RuntimeError("API down")
        # Subsequent calls (flux-schnell fallback) succeed
        return [fake]

    with patch("pipeline.agents.image_agent.replicate.run", side_effect=_replicate), \
         patch("pipeline.agents.image_agent.gemini_client") as mc:
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = fake_response
        mc.return_value = mock_client
        agent = ImageAgent(scene, equipment_type="laser", domain="lab", ref_path=ref)
        result = agent.run(out)

    # Should have at least tried both paths
    assert call_count["i"] >= 2


def test_image_agent_keeps_best_attempt_when_later_attempt_is_worse(tmp_path):
    """When attempt 1 scores higher than attempt 2 (both failing), the file
    on disk must match the higher-scoring attempt — not the last write."""
    ref = _make_fake_image(tmp_path)
    out = tmp_path / "out.png"

    # Two distinct image bytes so we can verify which one is kept
    bytes_attempt1 = b"\x89PNG\r\n\x1a\n" + b"\x01" * 200
    bytes_attempt2 = b"\x89PNG\r\n\x1a\n" + b"\x02" * 200

    fake1 = MagicMock(); fake1.read.return_value = bytes_attempt1
    fake2 = MagicMock(); fake2.read.return_value = bytes_attempt2

    rep_calls = {"i": 0}
    def _replicate(model, **kwargs):
        rep_calls["i"] += 1
        # flux-1.1-pro returns single FileOutput on attempt 1, then attempt 2
        return fake1 if rep_calls["i"] == 1 else fake2

    # Attempt 1: score 6.0 (fail), Attempt 2: score 4.0 (fail and worse)
    crit_high = {"anatomy": 6, "domain_match": 6, "no_split_screen": 6,
                 "equipment_match": 6, "composition": 6, "main_issue": "x", "retry_hint": "y"}
    crit_low = {"anatomy": 4, "domain_match": 4, "no_split_screen": 4,
                "equipment_match": 4, "composition": 4, "main_issue": "x", "retry_hint": "y"}
    crit_responses = [MagicMock(text=json.dumps(crit_high)),
                      MagicMock(text=json.dumps(crit_low))]
    crit_idx = {"i": 0}
    def _gemini(*args, **kwargs):
        i = crit_idx["i"]; crit_idx["i"] += 1
        return crit_responses[min(i, len(crit_responses) - 1)]

    refine_response = json.dumps({"refined_prompt": "refined prompt with extra detail",
                                  "what_changed": "x"})
    scene = {"scene_id": "S01", "act": "hook", "image_prompt": "lab"}

    with patch("pipeline.agents.image_agent.replicate.run", side_effect=_replicate), \
         patch("pipeline.agents.image_agent.gemini_client") as mc, \
         patch("pipeline.agents.image_agent.call_gemini_with_retry", return_value=refine_response):
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = _gemini
        mc.return_value = mock_client
        agent = ImageAgent(scene, equipment_type="laser", domain="lab",
                           ref_path=ref, max_attempts=2)
        result = agent.run(out)

    # Both attempts failed quality gate
    assert not result.passed
    # The reported best score must be the higher one (attempt 1)
    assert result.score == pytest.approx(6.0)
    assert result.attempts == 1  # best attempt was attempt 1
    # The file on disk must be attempt 1's bytes, NOT attempt 2's last-write
    assert out.read_bytes() == bytes_attempt1


def test_image_agent_reports_passed_false_when_score_below_threshold(tmp_path):
    """Even if generation succeeds, low score must mean passed=False."""
    ref = _make_fake_image(tmp_path)
    out = tmp_path / "out.png"
    fake = MagicMock()
    fake.read.return_value = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
    crit_fail = {"anatomy": 5, "domain_match": 5, "no_split_screen": 5,
                 "equipment_match": 5, "composition": 5,
                 "main_issue": "weak", "retry_hint": "improve"}
    fake_response = MagicMock(text=json.dumps(crit_fail))
    refine_response = json.dumps({"refined_prompt": "improved prompt with more detail",
                                  "what_changed": "x"})
    scene = {"scene_id": "S01", "act": "hook", "image_prompt": "lab"}

    with patch("pipeline.agents.image_agent.replicate.run", return_value=fake), \
         patch("pipeline.agents.image_agent.gemini_client") as mc, \
         patch("pipeline.agents.image_agent.call_gemini_with_retry", return_value=refine_response):
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = fake_response
        mc.return_value = mock_client
        agent = ImageAgent(scene, equipment_type="laser", domain="lab",
                           ref_path=ref, max_attempts=2)
        result = agent.run(out)

    assert result.success  # generation worked
    assert not result.passed  # but quality threshold not met
    assert result.score == pytest.approx(5.0)
    assert out.exists()
