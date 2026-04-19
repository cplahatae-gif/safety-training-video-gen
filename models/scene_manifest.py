from __future__ import annotations
from enum import Enum
from typing import Optional, Literal
from pydantic import BaseModel


class SceneStatus(str, Enum):
    pending = "pending"
    audio_ready = "audio_ready"
    image_ready = "image_ready"
    clip_ready = "clip_ready"
    merged_ready = "merged_ready"   # per-scene merge done; final concat pending
    assembled = "assembled"
    skipped = "skipped"


class Scene(BaseModel):
    scene_id: str
    act: str
    duration_sec: int
    status: SceneStatus = SceneStatus.pending
    narration_ko: str
    image_prompt: str
    motion_prompt: str
    camera: str
    mood: str
    on_screen_text: Optional[str] = None


class SceneManifest(BaseModel):
    sop_title: str
    total_duration_sec: int
    video_style: Literal["hybrid", "shortform"]
    tts_provider: Optional[str] = None
    tts_voice: Optional[str] = None
    scenes: list[Scene]

    def save(self, workspace: Path) -> None:
        """Persist manifest.json to workspace directory."""
        (workspace / "manifest.json").write_text(
            self.model_dump_json(indent=2), encoding="utf-8"
        )


class Hazard(BaseModel):
    id: str
    name: str
    severity: str


class ProcedureStep(BaseModel):
    step: int
    action: str
    key_rules: list[str]


class SopJson(BaseModel):
    sop_title: str
    legal_basis: list[str]
    hazards: list[Hazard]
    procedure_steps: list[ProcedureStep]
    target_audience: str
    common_violations: list[str]
