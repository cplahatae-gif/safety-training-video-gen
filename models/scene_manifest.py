from __future__ import annotations
from enum import Enum
from pathlib import Path
from typing import Optional, Literal
from pydantic import BaseModel, Field


class SceneStatus(str, Enum):
    pending = "pending"
    audio_ready = "audio_ready"
    image_ready = "image_ready"
    clip_ready = "clip_ready"
    merged_ready = "merged_ready"
    assembled = "assembled"
    skipped = "skipped"


# scene_id is used as a filename segment across the pipeline (audio, images,
# clips, merged, concat.txt). Restricting to alphanumerics + underscore/hyphen
# blocks path traversal, ffmpeg concat-list injection (single quotes, newlines),
# and Windows reserved characters.
_SCENE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,32}$"
_ACT_PATTERN = r"^[a-z_]{1,20}$"
# sop_title flows into output filenames; block control chars, path separators,
# and outright empty strings. Korean syllables (U+AC00..U+D7A3) allowed.
_SOP_TITLE_PATTERN = r"^[^\x00-\x1f/\\]{1,100}$"


class Scene(BaseModel):
    scene_id: str = Field(pattern=_SCENE_ID_PATTERN)
    act: str = Field(pattern=_ACT_PATTERN)
    duration_sec: int
    status: SceneStatus = SceneStatus.pending
    narration_ko: str = ""
    image_prompt: str
    motion_prompt: str
    camera: str
    mood: str
    on_screen_text: Optional[str] = None
    # BGM search keywords for this scene's tone (royalty-free library lookup).
    # Defaults to empty list for backwards compat with older manifests.
    bgm_keywords: list[str] = []


class SceneManifest(BaseModel):
    sop_title: str = Field(pattern=_SOP_TITLE_PATTERN)
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


_DOMAIN_LITERAL = Literal["industrial", "lab", "medical", "chemical", "construction", "general"]


class DeepExtract(BaseModel):
    """Detail-rich information extracted from SOP for richer scenario generation."""
    specific_hazards: list[str] = []
    specific_procedures: list[str] = []
    equipment_details: list[str] = []
    injury_types: list[str] = []
    thresholds: list[str] = []


class SopJson(BaseModel):
    sop_title: str = Field(pattern=_SOP_TITLE_PATTERN)
    legal_basis: list[str]
    hazards: list[Hazard]
    procedure_steps: list[ProcedureStep]
    target_audience: str
    common_violations: list[str]
    equipment_type: Optional[str] = None
    domain: _DOMAIN_LITERAL = "general"
    deep_extract: Optional[DeepExtract] = None
