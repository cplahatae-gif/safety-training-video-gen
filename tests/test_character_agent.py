"""Tests for CharacterAgent (Phase B) — multi-angle reference sheet."""
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from pipeline.agents.character_agent import (
    CharacterAgent,
    generate_sheet,
    select_for_scene,
    _ACT_POSE_MAP,
)
from prompts.character_prompts import (
    CHARACTER_PROMPTS,
    CHARACTER_SHEET_POSES,
    get_character_prefix,
    build_character_sheet_prompt,
    build_image_prompt_v2,
)


# ─── Domain prefix tests ──────────────────────────────────────────────────────


def test_each_domain_has_distinct_prefix():
    domains = ("industrial", "lab", "medical", "chemical", "construction", "general")
    prefixes = [CHARACTER_PROMPTS[d] for d in domains]
    # Each domain prefix should be unique (no two domains share text)
    assert len(set(prefixes)) == len(prefixes)


def test_lab_prefix_does_not_contain_industrial_keywords():
    """Lab character should NOT have hard hat or reflective vest."""
    lab = get_character_prefix("lab")
    assert "hard hat" not in lab.lower()
    assert "reflective" not in lab.lower()
    assert "lab coat" in lab.lower()


def test_industrial_prefix_has_safety_gear():
    industrial = get_character_prefix("industrial")
    assert "hard hat" in industrial.lower()
    assert "reflective" in industrial.lower()


def test_unknown_domain_falls_back_to_general():
    unknown = get_character_prefix("unicorn-domain")
    assert unknown == CHARACTER_PROMPTS["general"]


def test_build_image_prompt_v2_uses_domain_prefix(monkeypatch):
    prompt = build_image_prompt_v2("close-up of laser", domain="lab", equipment="Class 4 laser")
    assert "lab coat" in prompt.lower()
    assert "Class 4 laser" in prompt
    assert "close-up of laser" in prompt


# ─── Character sheet pose tests ───────────────────────────────────────────────


def test_character_sheet_has_5_poses():
    assert len(CHARACTER_SHEET_POSES) >= 5


def test_each_pose_has_id_and_description():
    for pose in CHARACTER_SHEET_POSES:
        assert "id" in pose
        assert "description" in pose
        assert pose["id"]
        assert len(pose["description"]) > 10


def test_build_character_sheet_prompt_includes_pose_and_prefix():
    pose = CHARACTER_SHEET_POSES[0]  # front pose
    prompt = build_character_sheet_prompt("lab", pose)
    assert pose["description"] in prompt
    assert "lab coat" in prompt.lower()


# ─── Sheet generation (mocked) ────────────────────────────────────────────────


def test_generate_sheet_creates_files_for_each_pose(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    fake_file = MagicMock()
    fake_file.read.return_value = fake_png

    with patch("pipeline.agents.character_agent.replicate.run") as mock_run:
        mock_run.return_value = [fake_file]
        sheet = generate_sheet("lab", workspace, equipment_hint="laser system")

    sheet_dir = workspace / "character_sheet"
    assert sheet_dir.exists()
    # Should have generated all poses
    assert len(sheet) == len(CHARACTER_SHEET_POSES)
    for pose in CHARACTER_SHEET_POSES:
        path = sheet_dir / f"{pose['id']}.png"
        assert path.exists(), f"Missing {pose['id']}"
        assert path.read_bytes() == fake_png


def test_generate_sheet_skips_existing_cached_files(tmp_path):
    workspace = tmp_path / "ws"
    sheet_dir = workspace / "character_sheet"
    sheet_dir.mkdir(parents=True)
    cached_png = sheet_dir / "front.png"
    cached_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 2000)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    fake_file = MagicMock()
    fake_file.read.return_value = fake_png

    with patch("pipeline.agents.character_agent.replicate.run") as mock_run:
        mock_run.return_value = [fake_file]
        sheet = generate_sheet("lab", workspace)

    # Front pose was cached, others were generated
    assert mock_run.call_count == len(CHARACTER_SHEET_POSES) - 1
    assert sheet["front"] == cached_png


def test_generate_sheet_returns_partial_on_failure(tmp_path):
    """If replicate.run raises persistently, those poses are skipped."""
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with patch("pipeline.agents.character_agent.replicate.run", side_effect=RuntimeError("API down")):
        sheet = generate_sheet("lab", workspace)

    assert sheet == {}


# ─── Scene-pose selection ─────────────────────────────────────────────────────


def test_select_for_scene_uses_act_heuristic(tmp_path):
    sheet = {p["id"]: tmp_path / f"{p['id']}.png" for p in CHARACTER_SHEET_POSES}

    # hook → front
    chosen = select_for_scene({"act": "hook"}, sheet)
    assert chosen == sheet["front"]

    # conflict → alert
    chosen = select_for_scene({"act": "conflict"}, sheet)
    assert chosen == sheet["alert"]

    # resolution → working
    chosen = select_for_scene({"act": "resolution"}, sheet)
    assert chosen == sheet["working"]


def test_select_for_scene_falls_back_when_pose_missing(tmp_path):
    """If preferred pose is not in sheet, fall back through default order."""
    # Sheet has no 'alert' but has 'working' and 'front'
    sheet = {
        "working": tmp_path / "working.png",
        "front": tmp_path / "front.png",
    }
    chosen = select_for_scene({"act": "conflict"}, sheet)  # prefers alert
    # Falls back to working (first in default order)
    assert chosen == sheet["working"]


def test_select_for_scene_returns_none_on_empty_sheet():
    chosen = select_for_scene({"act": "hook"}, {})
    assert chosen is None


def test_select_for_scene_unknown_act_falls_back(tmp_path):
    sheet = {p["id"]: tmp_path / f"{p['id']}.png" for p in CHARACTER_SHEET_POSES}
    chosen = select_for_scene({"act": "nonexistent_act"}, sheet)
    # Should still return something via default order
    assert chosen is not None
    assert chosen == sheet["working"]  # first in default fallback order


# ─── Agent class ──────────────────────────────────────────────────────────────


def test_character_agent_caches_sheet(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    fake_file = MagicMock()
    fake_file.read.return_value = fake_png

    with patch("pipeline.agents.character_agent.replicate.run") as mock_run:
        mock_run.return_value = [fake_file]
        agent = CharacterAgent(domain="lab", workspace=workspace)
        sheet1 = agent.prepare()
        sheet2 = agent.prepare()  # second call should not regenerate

    assert sheet1 == sheet2
    # First prepare() called replicate len(POSES) times; second prepare() no extra calls
    assert mock_run.call_count == len(CHARACTER_SHEET_POSES)


def test_character_agent_select_uses_prepared_sheet(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
    fake_file = MagicMock()
    fake_file.read.return_value = fake_png

    with patch("pipeline.agents.character_agent.replicate.run") as mock_run:
        mock_run.return_value = [fake_file]
        agent = CharacterAgent(domain="industrial", workspace=workspace)
        ref = agent.select({"act": "resolution"})

    assert ref is not None
    assert ref.name == "working.png"  # resolution → working pose
