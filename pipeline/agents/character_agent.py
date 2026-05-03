"""CharacterAgent — Identity Anchoring via multi-angle reference sheet.

Following arxiv 2512.16954 "Lights, Camera, Consistency":
- Generate a character reference sheet (5-6 angles/poses) BEFORE scene generation
- Each scene picks the most relevant pose as its FLUX image_prompt anchor
- This eliminates character drift across scenes

Workflow:
1. generate_sheet(domain, workspace) -> dict[str, Path]
   Generates character_sheet/{pose_id}.png for each pose
2. select_for_scene(scene, sheet_paths) -> Path
   Picks best-matching pose for each scene using Gemini Vision (or heuristic)

Mock-friendly: replicate.run is the only external dependency.
"""
from __future__ import annotations
import time
from pathlib import Path
from typing import Optional

import replicate
from rich.console import Console

import config
from pipeline.agents.reference_loader import ReferenceImages, load_references
from prompts.character_prompts import (
    CHARACTER_SHEET_POSES,
    build_character_sheet_prompt,
    get_character_prefix,
)

console = Console()

THROTTLE_MAX_RETRIES = 3
THROTTLE_DEFAULT_SLEEP = 6


def _is_throttle(exc: Exception) -> bool:
    msg = str(exc)
    return "429" in msg or "throttled" in msg.lower()


def _generate_one_pose(
    prompt: str,
    out_path: Path,
    model: str | None = None,
    ref_path: Path | None = None,
) -> bool:
    """Generate a single pose image. Uses FLUX-1.1-pro+ref when ref_path given,
    otherwise falls back to FLUX-schnell text-only."""
    if ref_path and ref_path.exists():
        return _generate_one_pose_with_ref(prompt, out_path, ref_path)

    model = model or config.DEFAULT_IMAGE_MODEL
    for attempt in range(THROTTLE_MAX_RETRIES + 1):
        try:
            output = replicate.run(
                model,
                input={
                    "prompt": prompt,
                    "aspect_ratio": "16:9",
                    "num_inference_steps": 4,
                    "num_outputs": 1,
                    "output_format": "png",
                },
            )
            data = (output[0].read() if isinstance(output, list) else output.read())
            if not data:
                raise ValueError("empty image bytes")
            out_path.write_bytes(data)
            return True
        except Exception as exc:
            if _is_throttle(exc) and attempt < THROTTLE_MAX_RETRIES:
                console.print(
                    f"[dim]Throttle on character sheet pose, sleep {THROTTLE_DEFAULT_SLEEP}s "
                    f"(retry {attempt + 1}/{THROTTLE_MAX_RETRIES})[/dim]"
                )
                time.sleep(THROTTLE_DEFAULT_SLEEP)
                continue
            console.print(f"[red]Pose gen failed for {out_path.name}: {exc}[/red]")
            return False
    return False


def _generate_one_pose_with_ref(prompt: str, out_path: Path, ref_path: Path) -> bool:
    """Generate pose using FLUX-1.1-pro with user reference image.

    Higher image_prompt_strength (0.25) than scene images (0.15) to lock in
    character identity during sheet generation.
    """
    model = config.REF_IMAGE_MODEL
    for attempt in range(THROTTLE_MAX_RETRIES + 1):
        try:
            with open(ref_path, "rb") as ref_file:
                output = replicate.run(
                    model,
                    input={
                        "prompt": prompt,
                        "aspect_ratio": "16:9",
                        "output_format": "png",
                        "image_prompt": ref_file,
                        "image_prompt_strength": 0.25,
                    },
                )
            data = output.read() if hasattr(output, "read") else output[0].read()
            if not data:
                raise ValueError("empty image bytes")
            out_path.write_bytes(data)
            return True
        except Exception as exc:
            if _is_throttle(exc) and attempt < THROTTLE_MAX_RETRIES:
                console.print(
                    f"[dim]Throttle (ref pose), sleep {THROTTLE_DEFAULT_SLEEP}s "
                    f"(retry {attempt + 1}/{THROTTLE_MAX_RETRIES})[/dim]"
                )
                time.sleep(THROTTLE_DEFAULT_SLEEP)
                continue
            console.print(f"[yellow]Ref pose failed ({exc}), retrying text-only[/yellow]")
            return _generate_one_pose(prompt, out_path)  # fallback to text-only
    return False


def generate_sheet(
    domain: str,
    workspace: Path,
    equipment_hint: str = "",
    references: Optional[ReferenceImages] = None,
) -> dict[str, Path]:
    """Generate the multi-angle character reference sheet.

    If `references` contains a person/uniform image, each pose is generated
    with FLUX-1.1-pro using that image as `image_prompt` (Option C: Identity
    Anchoring from real reference). Falls back to text-only FLUX-schnell when
    no references are provided.

    Returns a dict {pose_id: Path}.
    """
    sheet_dir = workspace / "character_sheet"
    sheet_dir.mkdir(parents=True, exist_ok=True)

    env_hint = f"context background hint: {equipment_hint}" if equipment_hint else ""
    ref_path = references.primary_character_path if references else None
    ref_desc = references.prompt_prefix() if references else ""

    if ref_path:
        console.print(
            f"[dim]Generating {len(CHARACTER_SHEET_POSES)}-pose character sheet "
            f"(domain={domain}, ref={ref_path.name})[/dim]"
        )
    else:
        console.print(
            f"[dim]Generating {len(CHARACTER_SHEET_POSES)}-pose character sheet "
            f"(domain={domain}, text-only)[/dim]"
        )

    sheet: dict[str, Path] = {}
    for pose in CHARACTER_SHEET_POSES:
        pose_id = pose["id"]
        out_path = sheet_dir / f"{pose_id}.png"
        if out_path.exists() and out_path.stat().st_size > 1024:
            sheet[pose_id] = out_path
            console.print(f"[dim]  ok {pose_id} (cached)[/dim]")
            continue

        prompt = build_character_sheet_prompt(domain, pose, env_hint, ref_desc=ref_desc)
        if _generate_one_pose(prompt, out_path, ref_path=ref_path):
            sheet[pose_id] = out_path
            console.print(f"[dim]  ok {pose_id}[/dim]")
        else:
            console.print(f"[yellow]  fail {pose_id} (skipped)[/yellow]")

    if not sheet:
        console.print(
            "[yellow]Warning: character sheet empty — falling back to text-only prompts[/yellow]"
        )
    return sheet


# ─── Per-scene reference selection ────────────────────────────────────────────


# Heuristic: map act → preferred pose
_ACT_POSE_MAP = {
    "hook": "front",
    "conflict": "alert",
    "consequence": "alert",
    "resolution": "working",
    "rules": "instructive",
}

_DEFAULT_FALLBACK_ORDER = ["working", "front", "instructive", "side", "alert"]


def select_for_scene(scene: dict, sheet: dict[str, Path]) -> Optional[Path]:
    """Pick the best pose from the sheet for a given scene.

    Strategy: act-based heuristic first, then fall back through the sheet.
    Returns None if the sheet is empty.
    """
    if not sheet:
        return None

    act = (scene.get("act") or "").lower()
    preferred = _ACT_POSE_MAP.get(act)
    if preferred and preferred in sheet:
        return sheet[preferred]

    # Fall back: try common poses in order
    for pose_id in _DEFAULT_FALLBACK_ORDER:
        if pose_id in sheet:
            return sheet[pose_id]

    # Last resort: any available pose
    return next(iter(sheet.values()))


# ─── Public CharacterAgent class ──────────────────────────────────────────────


class CharacterAgent:
    """Wraps generate_sheet + select_for_scene.

    Usage:
        agent = CharacterAgent(domain="lab", workspace=workspace, equipment_hint="...")
        agent.prepare()  # generates sheet (auto-loads references from REFERENCE_DIR)
        ref_path = agent.select(scene)  # per-scene selection
    """

    def __init__(
        self,
        domain: str,
        workspace: Path,
        equipment_hint: str = "",
        references: Optional[ReferenceImages] = None,
    ):
        self.domain = domain
        self.workspace = workspace
        self.equipment_hint = equipment_hint
        self.sheet: dict[str, Path] = {}
        self._prepared = False
        # Auto-load references from REFERENCE_DIR if not explicitly provided
        if references is None:
            references = load_references()
            if references.has_references:
                console.print(
                    f"[dim]Reference images loaded: "
                    f"{', '.join(references.paths.keys())}[/dim]"
                )
        self.references = references

    def prepare(self) -> dict[str, Path]:
        if self._prepared:
            return self.sheet
        self.sheet = generate_sheet(
            self.domain, self.workspace, self.equipment_hint, self.references
        )
        self._prepared = True
        return self.sheet

    def select(self, scene: dict) -> Optional[Path]:
        if not self._prepared:
            self.prepare()
        return select_for_scene(scene, self.sheet)

    def get_prefix(self) -> str:
        return get_character_prefix(self.domain)
