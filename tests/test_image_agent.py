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


def test_critique_handles_gemini_failure_gracefully(tmp_path):
    """If Gemini errors, critique returns a passing score (don't block)."""
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
    assert result.passed
    assert result.score >= 7.0


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
    assert result.attempts == 1
    assert out.exists()


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
    # File still exists from last attempt
    assert out.exists()


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
