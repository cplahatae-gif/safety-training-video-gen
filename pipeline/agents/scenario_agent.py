"""ScenarioAgent — research-backed plan-then-generate scenario builder.

Pipeline:
1. enrich_sop: detect domain + extract deep info
2. _generate_treatment: detailed prose treatment (length scales with duration)
3. _generate_scenes: cut treatment into rich JSON scenes (with bgm_keywords)
4. _critique: self-evaluate (Gemini text)
5. _refine: regenerate if score < threshold (max 2 attempts)

The treatment is saved to `workspace/treatment.md` so a human can review it
before scenes are cut. Scenes carry empty narration (visual + BGM + on-screen
text only); narration TTS is a future layer.

Output: list[dict] — same format as legacy generate_script() for backwards compat.
"""
from __future__ import annotations
import json
from pathlib import Path
from typing import Optional

from rich.console import Console

import config
from pipeline.agents.base_agent import (
    BaseAgent,
    CritiqueResult,
    call_gemini_with_retry,
    parse_json_response,
)
from pipeline.agents.sop_extractor import enrich_sop
from prompts.scenario_brief_prompt import TREATMENT_PROMPT
from prompts.scenario_rich_prompt import RICH_SCENES_PROMPT
from prompts.scenario_critique_prompt import CRITIQUE_PROMPT
from prompts.script_prompt import _FORBIDDEN_WORDS, REQUIRED_ACTS

console = Console()

# Treatment length scales with video duration. ~150 chars per second of video.
# 30s -> 4500 chars, 180s -> 27000 chars. Floor at 2500 to avoid trivial output.
TREATMENT_CHARS_PER_SEC = 150
TREATMENT_MIN_CHARS = 2500


def _bullet_list(items: list[str], max_items: int = 8) -> str:
    """Format list as numbered bullets, truncated to max_items."""
    if not items:
        return "(정보 없음)"
    lines = [f"- {item}" for item in items[:max_items]]
    return "\n".join(lines)


class ScenarioAgent(BaseAgent):
    """Generate a rich scene list from SOP using plan-then-generate pattern."""

    name = "ScenarioAgent"

    def __init__(self, sop: dict, duration: int, workspace: Optional[Path] = None):
        self.sop = sop
        self.duration = duration
        self.workspace = workspace
        self.treatment: str = ""
        self._enriched = False

    # ─── Public entry ─────────────────────────────────────────────────────────

    def run_scenes(self) -> list[dict]:
        """Public method: returns list of scene dicts (legacy-compatible format).

        Side effect: writes `treatment.md` to workspace if workspace is set.
        """
        # Step 1: Enrich SOP with domain + deep_extract
        if not self._enriched:
            enrich_sop(self.sop)
            self._enriched = True

        # Step 2: Generate detailed treatment (cached on self.treatment)
        self.treatment = self.generate_treatment()
        if self.workspace is not None:
            try:
                self.workspace.mkdir(parents=True, exist_ok=True)
                (self.workspace / "treatment.md").write_text(
                    self.treatment, encoding="utf-8"
                )
                console.print(
                    f"[green]Treatment saved: {self.workspace / 'treatment.md'} "
                    f"({len(self.treatment)} chars)[/green]"
                )
            except Exception as exc:
                console.print(f"[yellow]Could not save treatment.md: {exc}[/yellow]")

        # Step 3-5: BaseAgent's run() handles generate/critique/refine loop
        scenes, critique = self.run(input_data=None)
        console.print(f"[dim]Scenario complete: score {critique.score:.1f}/10[/dim]")
        return scenes

    # ─── Treatment generation ────────────────────────────────────────────────

    def generate_treatment(self) -> str:
        """Generate a detailed prose treatment of the full video.

        Length scales with self.duration (~150 chars/sec, floor 2500). The
        treatment is what a human reviews before scenes are cut.
        """
        target_chars = max(TREATMENT_MIN_CHARS, self.duration * TREATMENT_CHARS_PER_SEC)
        deep = self.sop.get("deep_extract") or {}
        prompt = TREATMENT_PROMPT.format(
            duration=self.duration,
            target_chars=target_chars,
            sop_title=self.sop.get("sop_title", ""),
            domain=self.sop.get("domain", "general"),
            equipment_type=self.sop.get("equipment_type") or "(미기재)",
            target_audience=self.sop.get("target_audience", ""),
            specific_hazards=_bullet_list(deep.get("specific_hazards", [])),
            specific_procedures=_bullet_list(deep.get("specific_procedures", [])),
            injury_types=_bullet_list(deep.get("injury_types", [])),
            thresholds=_bullet_list(deep.get("thresholds", [])),
        )
        text = call_gemini_with_retry(prompt)
        treatment = text.strip()
        console.print(
            f"[dim]Treatment generated ({len(treatment)} chars, target ~{target_chars})[/dim]"
        )
        return treatment

    # ─── BaseAgent overrides ──────────────────────────────────────────────────

    def _generate(self, input_data) -> list[dict]:
        """Cut the treatment into rich scene cards (with bgm_keywords)."""
        deep = self.sop.get("deep_extract") or {}
        # Compute scene_count and resolution_count based on duration
        scene_count = max(5, self.duration // 5)  # 5-second target per scene
        # Resolution gets proportionally more scenes (research says explanation needs time)
        if scene_count <= 5:
            resolution_count = "1-2"
        elif scene_count <= 8:
            resolution_count = "2-3"
        else:
            resolution_count = "3-4"

        prompt = RICH_SCENES_PROMPT.format(
            treatment=self.treatment,
            sop_title=self.sop.get("sop_title", ""),
            domain=self.sop.get("domain", "general"),
            equipment_type=self.sop.get("equipment_type") or "(미기재)",
            specific_hazards=_bullet_list(deep.get("specific_hazards", []), max_items=5),
            specific_procedures=_bullet_list(deep.get("specific_procedures", []), max_items=5),
            injury_types=_bullet_list(deep.get("injury_types", []), max_items=3),
            thresholds=_bullet_list(deep.get("thresholds", []), max_items=3),
            scene_count=scene_count,
            resolution_count=resolution_count,
        )
        text = call_gemini_with_retry(prompt)
        scenes = parse_json_response(text)
        if not isinstance(scenes, list):
            raise ValueError(f"Expected JSON array, got {type(scenes).__name__}")
        return scenes

    def _critique(self, scenes: list[dict]) -> CritiqueResult:
        """Self-evaluate the generated scenes using Gemini text."""
        # Quick deterministic checks first (no API call needed)
        det_issues: list[str] = []
        has_forbidden = False
        has_schema_violation = False
        # Required keys per scene (downstream split_scenes / Scene model both need these).
        # narration_ko is intentionally NOT required — it's left empty in this flow.
        required_keys = ("scene_id", "act", "image_prompt", "motion_prompt")
        for i, s in enumerate(scenes):
            missing_keys = [k for k in required_keys if not s.get(k)]
            if missing_keys:
                sid = s.get("scene_id") or f"index{i}"
                det_issues.append(f"{sid}: 필수 키 누락/빈 값 {missing_keys}")
                has_schema_violation = True
            # bgm_keywords should be a non-empty list
            bgm = s.get("bgm_keywords")
            if not isinstance(bgm, list) or not bgm:
                sid = s.get("scene_id") or f"index{i}"
                det_issues.append(f"{sid}: bgm_keywords 누락 또는 빈 배열")
                has_schema_violation = True
        acts = {s.get("act", "") for s in scenes}
        missing = REQUIRED_ACTS - acts
        if missing:
            det_issues.append(f"누락된 액트: {sorted(missing)}")
        for s in scenes:
            ip = (s.get("image_prompt") or "").lower()
            for w in _FORBIDDEN_WORDS:
                if w in ip:
                    det_issues.append(f"{s.get('scene_id')}: 금지어 '{w}' in image_prompt")
                    has_forbidden = True

        # Gemini eval — narration is intentionally empty in this flow;
        # surface image_prompt + on_screen_text + bgm_keywords instead.
        def _scene_line(s: dict) -> str:
            sid = s.get("scene_id", "?")
            act = s.get("act", "?")
            ost = s.get("on_screen_text") or "(no text)"
            ip = (s.get("image_prompt") or "")[:140]
            bgm = ", ".join(s.get("bgm_keywords") or []) or "(no bgm)"
            return f"[{sid}] {act} | text='{ost}' | bgm=[{bgm}]\n  image_prompt: {ip}"
        scenes_summary = "\n".join(_scene_line(s) for s in scenes)
        deep = self.sop.get("deep_extract") or {}
        prompt = CRITIQUE_PROMPT.format(
            sop_title=self.sop.get("sop_title", ""),
            equipment_type=self.sop.get("equipment_type") or "(미기재)",
            domain=self.sop.get("domain", "general"),
            specific_hazards=_bullet_list(deep.get("specific_hazards", []), max_items=5),
            specific_procedures=_bullet_list(deep.get("specific_procedures", []), max_items=5),
            scenes_summary=scenes_summary,
        )
        try:
            text = call_gemini_with_retry(prompt)
            result = parse_json_response(text)
            critique = CritiqueResult.from_dict(result, threshold=self.threshold)
            # Merge deterministic issues
            critique.issues = det_issues + critique.issues
            # Penalize if deterministic violations exist
            if det_issues:
                penalty = min(len(det_issues) * 1.5, 5.0)
                critique.score = max(0.0, critique.score - penalty)
                critique.passed = critique.score >= self.threshold
            # Forbidden words OR schema violation = critical, always fail
            if has_forbidden or has_schema_violation:
                critique.passed = False
            return critique
        except Exception as exc:
            console.print(f"[yellow]Critique failed ({exc}) — accepting with no critique[/yellow]")
            score = 5.0 if det_issues else 8.0
            return CritiqueResult(
                score=score,
                issues=det_issues,
                raw={},
                passed=score >= self.threshold,
            )

    def _refine(self, scenes: list[dict], issues: list[str]) -> list[dict]:
        """Refine by re-generating with issues as additional instruction."""
        deep = self.sop.get("deep_extract") or {}
        scene_count = max(5, self.duration // 5)
        resolution_count = "2-3" if scene_count > 5 else "1-2"

        issues_block = "\n".join(f"- {i}" for i in issues[:5])
        refine_addendum = f"\n\n[이전 시도의 문제점 — 반드시 수정]\n{issues_block}\n위 문제를 모두 해결하세요.\n"

        prompt = RICH_SCENES_PROMPT.format(
            treatment=self.treatment,
            sop_title=self.sop.get("sop_title", ""),
            domain=self.sop.get("domain", "general"),
            equipment_type=self.sop.get("equipment_type") or "(미기재)",
            specific_hazards=_bullet_list(deep.get("specific_hazards", []), max_items=5),
            specific_procedures=_bullet_list(deep.get("specific_procedures", []), max_items=5),
            injury_types=_bullet_list(deep.get("injury_types", []), max_items=3),
            thresholds=_bullet_list(deep.get("thresholds", []), max_items=3),
            scene_count=scene_count,
            resolution_count=resolution_count,
        ) + refine_addendum

        text = call_gemini_with_retry(prompt)
        return parse_json_response(text)


# ─── Convenience function (drop-in replacement for legacy generate_script) ──


def generate_script_v2(
    sop: dict, duration: int, workspace: Optional[Path] = None
) -> list[dict]:
    """Drop-in replacement for pipeline.script_gen.generate_script using ScenarioAgent.

    If `workspace` is provided, the agent saves treatment.md there for human review.
    """
    agent = ScenarioAgent(sop, duration, workspace=workspace)
    return agent.run_scenes()
