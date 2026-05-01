"""Agent dry-run validator — exercises agent code paths with mocks.

NO actual Gemini/FLUX/Kling calls. Verifies that:
1. ScenarioAgent runs through brief → JSON → critique → return
2. CharacterAgent generates sheet, picks scene poses
3. ImageAgent runs critique loop

Usage:
    uv run python scripts/agent_dry_run.py
"""
from __future__ import annotations
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

# Allow import from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console

console = Console()


def dry_run_scenario_agent():
    from pipeline.agents.scenario_agent import generate_script_v2

    sample_sop = {
        "sop_title": "테스트 SOP",
        "legal_basis": [],
        "hazards": [],
        "procedure_steps": [{"step": 1, "action": "x", "key_rules": []}],
        "target_audience": "test",
        "common_violations": [],
        "equipment_type": "test equipment",
        "domain": "lab",
        "deep_extract": {
            "specific_hazards": ["test"],
            "specific_procedures": ["test"],
            "equipment_details": [],
            "injury_types": [],
            "thresholds": [],
        },
    }

    fake_brief = "테스트 brief 한 단락."
    fake_scenes = [
        {"scene_id": "S01", "act": "hook", "narration_ko": "테스트", "image_prompt": "test image",
         "motion_prompt": "test motion", "camera": "wide", "mood": "tense", "on_screen_text": None},
        {"scene_id": "S02", "act": "conflict", "narration_ko": "x", "image_prompt": "y",
         "motion_prompt": "z", "camera": "close", "mood": "warning", "on_screen_text": "위험"},
        {"scene_id": "S03", "act": "consequence", "narration_ko": "x", "image_prompt": "y",
         "motion_prompt": "z", "camera": "close", "mood": "serious", "on_screen_text": None},
        {"scene_id": "S04", "act": "resolution", "narration_ko": "x", "image_prompt": "y",
         "motion_prompt": "z", "camera": "close", "mood": "instructive", "on_screen_text": "OK"},
        {"scene_id": "S05", "act": "rules", "narration_ko": "x", "image_prompt": "y",
         "motion_prompt": "z", "camera": "wide", "mood": "calm", "on_screen_text": "준수"},
    ]
    fake_critique = {
        "specificity": 9, "act_coverage": 10, "equipment_lock": 8,
        "safety_accuracy": 9, "visual_clarity": 9, "issues": [],
    }
    responses = [fake_brief, json.dumps(fake_scenes), json.dumps(fake_critique)]
    idx = {"i": 0}

    def _fake(prompt, **kwargs):
        i = idx["i"]
        idx["i"] += 1
        return responses[min(i, len(responses) - 1)]

    with patch("pipeline.agents.scenario_agent.call_gemini_with_retry", side_effect=_fake), \
         patch("pipeline.agents.sop_extractor.enrich_sop", return_value=sample_sop):
        scenes = generate_script_v2(sample_sop, duration=30)

    assert len(scenes) == 5
    assert scenes[0]["scene_id"] == "S01"
    console.print("[green]PASS[/green] ScenarioAgent dry-run")


def dry_run_character_agent():
    from pipeline.agents.character_agent import CharacterAgent

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
        fake_file = MagicMock()
        fake_file.read.return_value = fake_png

        with patch("pipeline.agents.character_agent.replicate.run") as mock_run:
            mock_run.return_value = [fake_file]
            agent = CharacterAgent(domain="lab", workspace=workspace)
            sheet = agent.prepare()
            ref = agent.select({"act": "resolution"})

        assert len(sheet) == 5
        assert ref is not None and ref.name == "working.png"
    console.print("[green]PASS[/green] CharacterAgent dry-run")


def dry_run_image_agent():
    from pipeline.agents.image_agent import ImageAgent

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        ref = workspace / "ref.png"
        ref.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 200)
        out = workspace / "out.png"

        fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200
        fake_file = MagicMock()
        fake_file.read.return_value = fake_png
        fake_critique = {
            "anatomy": 9, "domain_match": 9, "no_split_screen": 10,
            "equipment_match": 9, "composition": 9,
            "main_issue": None, "retry_hint": None,
        }
        fake_response = MagicMock()
        fake_response.text = json.dumps(fake_critique)

        with patch("pipeline.agents.image_agent.replicate.run", return_value=fake_file), \
             patch("pipeline.agents.image_agent.gemini_client") as mc:
            mock_client = MagicMock()
            mock_client.models.generate_content.return_value = fake_response
            mc.return_value = mock_client
            agent = ImageAgent(
                {"scene_id": "S01", "act": "hook", "image_prompt": "test"},
                equipment_type="test", domain="lab", ref_path=ref,
            )
            result = agent.run(out)

        assert result.success
        assert result.score >= 7.0
    console.print("[green]PASS[/green] ImageAgent dry-run")


def main():
    console.rule("[bold]Agent dry-run (no real API calls)[/bold]")
    dry_run_scenario_agent()
    dry_run_character_agent()
    dry_run_image_agent()
    console.print("\n[bold green]All agents validated successfully.[/bold green]")


if __name__ == "__main__":
    main()
