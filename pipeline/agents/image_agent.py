"""ImageAgent — generate scene image with vision self-critique loop.

Pattern:
1. Generate v1 (FLUX-1.1-pro with character sheet ref OR FLUX-schnell)
2. Critique with Gemini Vision (anatomy / domain / composition / etc.)
3. If score < threshold:
   - Refine prompt (Gemini suggests fixes based on issues)
   - Regenerate with refined prompt
4. Return best (output_path, critique_score)

Up to 2 retries. If all attempts < threshold, returns the highest-scoring result.
This module is mock-friendly: replicate.run + Gemini calls are the only externals.
"""
from __future__ import annotations
import base64
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import replicate
from google.genai import types
from rich.console import Console

import config
from pipeline.agents.base_agent import (
    CritiqueResult,
    PASS_THRESHOLD,
    call_gemini_with_retry,
    gemini_client,
    parse_json_response,
    throttle_sleep_seconds,
)
from prompts.image_critique_prompt import (
    IMAGE_CRITIQUE_PROMPT,
    REFINE_PROMPT_HINT_PROMPT,
)

console = Console()

THROTTLE_MAX_RETRIES = 5
DEFAULT_MAX_ATTEMPTS = 2  # 1 initial + 1 refine


# ─── Generation backends ──────────────────────────────────────────────────────


def _flux_schnell(prompt: str, out_path: Path, model: str | None = None) -> bool:
    """Pure text-to-image FLUX call (no reference). Returns True on success."""
    model = model or config.DEFAULT_IMAGE_MODEL
    for attempt in range(config.MAX_RETRY + 1):
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
            sleep_s = throttle_sleep_seconds(exc)
            if sleep_s is not None and attempt < config.MAX_RETRY:
                time.sleep(sleep_s)
                continue
            if attempt == config.MAX_RETRY:
                console.print(f"[red]flux-schnell error: {exc}[/red]")
                return False
    return False


def _flux_pro_with_ref(
    prompt: str, ref_path: Path, out_path: Path, model: str | None = None
) -> bool:
    """FLUX-1.1-pro with a reference image. Returns True on success."""
    model = model or config.REF_IMAGE_MODEL
    for attempt in range(config.MAX_RETRY + 1):
        try:
            with open(ref_path, "rb") as ref_file:
                output = replicate.run(
                    model,
                    input={
                        "prompt": prompt,
                        "aspect_ratio": "16:9",
                        "output_format": "png",
                        "image_prompt": ref_file,
                        "image_prompt_strength": 0.15,
                    },
                )
            data = (output.read() if hasattr(output, "read") else output[0].read())
            if not data:
                raise ValueError("empty image bytes")
            out_path.write_bytes(data)
            return True
        except Exception as exc:
            sleep_s = throttle_sleep_seconds(exc)
            if sleep_s is not None and attempt < config.MAX_RETRY:
                time.sleep(sleep_s)
                continue
            if attempt == config.MAX_RETRY:
                console.print(f"[red]flux-1.1-pro+ref error: {exc}[/red]")
                return False
    return False


# ─── Vision critique ──────────────────────────────────────────────────────────


def _critique_image_with_vision(
    image_path: Path,
    *,
    image_prompt: str,
    act: str,
    equipment_type: str,
    domain: str,
) -> CritiqueResult:
    """Send the generated image to Gemini Vision for evaluation.

    Returns CritiqueResult with score = avg of per-metric scores.
    On Gemini failure, fails closed (score=0, passed=False) so the
    pipeline does not silently ship unreviewed images. Operators can set
    ALLOW_CRITIQUE_FALLBACK=1 to revert to the old fail-open behavior
    when Gemini is genuinely unavailable.
    """
    try:
        with open(image_path, "rb") as f:
            img_bytes = f.read()
    except Exception as exc:
        console.print(f"[yellow]Cannot read image for critique: {exc}[/yellow]")
        return CritiqueResult(score=0.0, issues=[str(exc)], raw={}, passed=False)

    prompt_text = IMAGE_CRITIQUE_PROMPT.format(
        equipment_type=equipment_type or "(미기재)",
        act=act,
        domain=domain,
        image_prompt=image_prompt[:200],
    )

    try:
        client = gemini_client()
        response = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                prompt_text,
            ],
        )
        text = response.text or ""
        result = parse_json_response(text)
        # Build CritiqueResult
        critique = CritiqueResult.from_dict(result, threshold=PASS_THRESHOLD)
        # Custom: collect main_issue + retry_hint into issues for refine step
        if result.get("main_issue") and result["main_issue"] not in (None, "null"):
            critique.issues.append(str(result["main_issue"]))
        return critique
    except Exception as exc:
        if os.environ.get("ALLOW_CRITIQUE_FALLBACK") == "1":
            console.print(
                f"[yellow]Vision critique failed: {exc} — ALLOW_CRITIQUE_FALLBACK=1 set, "
                f"accepting image[/yellow]"
            )
            return CritiqueResult(
                score=8.0,
                issues=[f"critique unavailable (fallback): {exc}"],
                raw={},
                passed=True,
            )
        console.print(
            f"[red]Vision critique unavailable: {exc} — failing closed "
            f"(set ALLOW_CRITIQUE_FALLBACK=1 to override)[/red]"
        )
        return CritiqueResult(
            score=0.0,
            issues=[f"critique unavailable: {exc}"],
            raw={},
            passed=False,
        )


# ─── Prompt refinement ────────────────────────────────────────────────────────


def _refine_prompt(original_prompt: str, issues: list[str]) -> str:
    """Ask Gemini to refine the image prompt given the critique issues."""
    if not issues:
        return original_prompt

    issues_text = "\n".join(f"- {i}" for i in issues[:5])
    prompt = REFINE_PROMPT_HINT_PROMPT.format(
        original_prompt=original_prompt,
        issues=issues_text,
    )
    try:
        text = call_gemini_with_retry(prompt)
        result = parse_json_response(text)
        refined = result.get("refined_prompt", original_prompt)
        if not refined or len(refined) < 20:
            return original_prompt
        return refined
    except Exception as exc:
        console.print(f"[yellow]Prompt refinement failed: {exc} — keeping original[/yellow]")
        return original_prompt


# ─── ImageAgent ───────────────────────────────────────────────────────────────


@dataclass
class ImageAgentResult:
    """Result of one ImageAgent.run().

    success — generation backend produced a file (no API outage).
    passed  — quality gate cleared (final image score >= threshold).

    Callers that decide whether to promote a scene to image_ready must check
    `passed`, not `success`. `success=True, passed=False` means a file exists
    on disk but did not clear vision critique — usually a signal to skip.
    """
    success: bool
    passed: bool
    score: float
    attempts: int
    final_prompt: str
    issues: list[str] = field(default_factory=list)


class ImageAgent:
    """Generate one scene's image with vision self-critique loop.

    Usage:
        agent = ImageAgent(scene_dict, equipment_type, domain, ref_path)
        result = agent.run(out_path)
    """

    def __init__(
        self,
        scene: dict,
        equipment_type: str = "",
        domain: str = "industrial",
        ref_path: Optional[Path] = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        threshold: float = PASS_THRESHOLD,
    ):
        self.scene = scene
        self.equipment_type = equipment_type
        self.domain = domain
        self.ref_path = ref_path
        self.max_attempts = max_attempts
        self.threshold = threshold
        self.scene_id = scene.get("scene_id", "unknown")
        self.act = scene.get("act", "unknown")
        self.image_prompt = scene.get("image_prompt", "")

    # ─── Internal generation step ─────────────────────────────────────────────

    def _generate_one(self, prompt: str, out_path: Path) -> bool:
        """Pick the right backend and generate one image."""
        if self.ref_path and self.ref_path.exists():
            success = _flux_pro_with_ref(prompt, self.ref_path, out_path)
            if success:
                return True
            console.print(f"[yellow]{self.scene_id}: ref model failed, falling back to schnell[/yellow]")
        return _flux_schnell(prompt, out_path)

    # ─── Public entry ─────────────────────────────────────────────────────────

    def run(self, out_path: Path) -> ImageAgentResult:
        """Generate-critique-refine loop.

        Each attempt writes to its own attempt-specific path so the best
        scoring artifact is preserved even if a later retry scores worse.
        At the end, the best attempt is copied to `out_path`.
        """
        current_prompt = self.image_prompt
        best_score = -1.0
        best_attempts = 0
        best_issues: list[str] = []
        best_path: Optional[Path] = None
        best_prompt = current_prompt
        attempt_paths: list[Path] = []
        any_generation_ok = False

        workdir = out_path.parent
        stem = out_path.stem

        for attempt in range(1, self.max_attempts + 1):
            attempt_path = workdir / f"{stem}.attempt{attempt}.png"
            attempt_paths.append(attempt_path)

            ok = self._generate_one(current_prompt, attempt_path)
            if not ok:
                if attempt >= self.max_attempts and not any_generation_ok:
                    self._cleanup_attempts(attempt_paths, keep=None)
                    return ImageAgentResult(
                        success=False, passed=False, score=0.0, attempts=attempt,
                        final_prompt=current_prompt,
                        issues=["generation backend failed"],
                    )
                continue
            any_generation_ok = True

            critique = _critique_image_with_vision(
                attempt_path,
                image_prompt=current_prompt,
                act=self.act,
                equipment_type=self.equipment_type,
                domain=self.domain,
            )
            console.print(
                f"[dim]{self.scene_id} attempt {attempt}: score {critique.score:.1f}/10[/dim]"
            )

            if critique.score > best_score:
                best_score = critique.score
                best_attempts = attempt
                best_issues = critique.issues
                best_path = attempt_path
                best_prompt = current_prompt

            if critique.passed:
                # Promote this attempt's file to the canonical out_path
                self._promote(attempt_path, out_path)
                self._cleanup_attempts(attempt_paths, keep=out_path)
                return ImageAgentResult(
                    success=True, passed=True, score=critique.score,
                    attempts=attempt, final_prompt=current_prompt,
                    issues=critique.issues,
                )

            # Below threshold; refine and retry if attempts remain
            if attempt < self.max_attempts:
                current_prompt = _refine_prompt(current_prompt, critique.issues)
                console.print(f"[dim]{self.scene_id}: refining prompt for retry[/dim]")

        # All attempts exhausted, none passed. Promote the best one anyway
        # so downstream stages have a file, but report passed=False so the
        # caller can decide to skip / human-review.
        if best_path and best_path.exists():
            self._promote(best_path, out_path)
        self._cleanup_attempts(attempt_paths, keep=out_path)

        return ImageAgentResult(
            success=any_generation_ok,
            passed=False,
            score=max(best_score, 0.0),
            attempts=best_attempts or self.max_attempts,
            final_prompt=best_prompt,
            issues=best_issues,
        )

    @staticmethod
    def _promote(src: Path, dst: Path) -> None:
        """Copy `src` to `dst`, overwriting if needed."""
        if src == dst or not src.exists():
            return
        shutil.copy2(src, dst)

    @staticmethod
    def _cleanup_attempts(paths: list[Path], keep: Optional[Path]) -> None:
        """Delete attempt-specific files, except `keep` (usually the canonical out_path)."""
        keep_resolved = keep.resolve() if keep else None
        for p in paths:
            try:
                if not p.exists():
                    continue
                if keep_resolved and p.resolve() == keep_resolved:
                    continue
                p.unlink()
            except Exception:
                pass
