"""ReferenceLoader — load user-provided reference images and describe them.

Usage:
    Place images in samples/references/:
      person.jpg     — character appearance (most important)
      uniform.jpg    — company uniform / PPE detail
      equipment.jpg  — specific equipment to match

    refs = load_references()          # loads from config.REFERENCE_DIR
    desc = refs.description           # text description for prompt injection
    char = refs.primary_character_path  # best image for FLUX image_prompt
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import config

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# Filename stems that map to each reference type (case-insensitive)
_TYPE_KEYWORDS: dict[str, list[str]] = {
    "person":    ["person", "character", "worker", "사람", "작업자", "인물"],
    "uniform":   ["uniform", "유니폼", "복장", "outfit", "vest"],
    "equipment": ["equipment", "장비", "tool", "도구"],
}


@dataclass
class ReferenceImages:
    """Container for all user-provided reference images."""
    paths: dict[str, Path] = field(default_factory=dict)   # {type: path}
    description: str = ""                                   # Gemini Vision text
    raw_description: dict = field(default_factory=dict)    # per-type text

    @property
    def has_references(self) -> bool:
        return bool(self.paths)

    @property
    def primary_character_path(self) -> Optional[Path]:
        """Return best image for FLUX image_prompt (person > uniform > first)."""
        for key in ("person", "uniform", "character", "worker"):
            if key in self.paths:
                return self.paths[key]
        return next(iter(self.paths.values()), None) if self.paths else None

    def prompt_prefix(self) -> str:
        """Short text prefix to prepend to image prompts when references exist."""
        if self.description:
            return self.description + ", "
        return ""


def load_references(reference_dir: Optional[Path] = None) -> ReferenceImages:
    """Scan reference_dir and load all image files.

    Auto-classifies by filename. Unknown filenames are stored under their stem.
    Returns an empty ReferenceImages (has_references=False) if directory
    doesn't exist or contains no images.
    """
    ref_dir = Path(reference_dir or config.REFERENCE_DIR)
    if not ref_dir.exists():
        return ReferenceImages()

    paths: dict[str, Path] = {}
    for img_path in sorted(ref_dir.iterdir()):
        if img_path.suffix.lower() not in _IMAGE_EXTS:
            continue
        stem = img_path.stem.lower()
        matched = False
        for ref_type, keywords in _TYPE_KEYWORDS.items():
            if any(kw in stem for kw in keywords):
                paths[ref_type] = img_path
                matched = True
                break
        if not matched:
            paths[stem] = img_path

    if not paths:
        return ReferenceImages()

    refs = ReferenceImages(paths=paths)

    # Describe with Gemini Vision only if explicitly enabled (costs a call)
    if os.environ.get("REFERENCE_DESCRIBE") == "1":
        refs.description = _describe_with_gemini(refs)
    else:
        # Build a compact text description from filenames for prompt injection
        refs.description = _build_text_description(refs)

    return refs


def _build_text_description(refs: ReferenceImages) -> str:
    """Build a text description without Gemini (cheap fallback).

    Injects a note that reference images are available so FLUX prompts
    know to match the reference appearance.
    """
    parts = []
    if "person" in refs.paths or "character" in refs.paths or "worker" in refs.paths:
        parts.append("matching the provided reference character appearance exactly")
    if "uniform" in refs.paths:
        parts.append("wearing the exact uniform shown in reference")
    if "equipment" in refs.paths:
        parts.append("with equipment matching the reference image")
    return ", ".join(parts) if parts else "matching provided reference images"


def _describe_with_gemini(refs: ReferenceImages) -> str:
    """Use Gemini Vision to describe reference images for richer prompt injection."""
    try:
        from google.genai import types
        from pipeline.agents.base_agent import gemini_client

        client = gemini_client()
        contents = []

        for ref_type, path in refs.paths.items():
            with open(path, "rb") as f:
                img_bytes = f.read()
            ext = path.suffix.lower().lstrip(".")
            mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
            contents.append(types.Part.from_bytes(data=img_bytes, mime_type=mime))

        contents.append(
            "Describe this person's appearance for an image generation prompt. "
            "Focus on: face features, hair, skin tone, clothing/uniform details, "
            "safety equipment. Be specific and concise (max 80 words). "
            "Output only the description, no extra text."
        )

        response = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=contents,
        )
        return (response.text or "").strip()
    except Exception as exc:
        from rich.console import Console
        Console().print(f"[yellow]Reference description failed: {exc}[/yellow]")
        return _build_text_description(refs)
