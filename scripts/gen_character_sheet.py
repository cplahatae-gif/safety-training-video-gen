"""One-off helper: generate the CharacterAgent reference sheet for a given run.

Use when you want to validate Identity Anchoring (5-pose sheet, ~$0.02)
before committing to full Stage 4 image generation (~$0.20-0.40).

Usage:
    uv run python scripts/gen_character_sheet.py <run_id> [domain]
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from pipeline.agents.character_agent import CharacterAgent


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: gen_character_sheet.py <run_id> [domain]")
        sys.exit(2)
    run_id = sys.argv[1]
    workspace = config.WORKSPACE_DIR / run_id
    if not workspace.exists():
        print(f"workspace not found: {workspace}")
        sys.exit(1)

    sop_path = workspace / "sop.json"
    domain = "general"
    equipment = ""
    if sop_path.exists():
        sop = json.loads(sop_path.read_text(encoding="utf-8"))
        domain = sop.get("domain") or "general"
        equipment = sop.get("equipment_type") or ""
    if len(sys.argv) >= 3:
        domain = sys.argv[2]

    print(f"Run: {run_id}")
    print(f"Domain: {domain}")
    print(f"Equipment hint: {equipment[:120]}")
    print()

    agent = CharacterAgent(domain=domain, workspace=workspace, equipment_hint=equipment)
    sheet = agent.prepare()

    print()
    print(f"Sheet has {len(sheet)} poses:")
    for pose_id, path in sheet.items():
        print(f"  {pose_id}: {path}")


if __name__ == "__main__":
    main()
