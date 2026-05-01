"""ScenarioAgent — research-backed plan-then-generate scenario builder.

Pipeline:
1. enrich_sop: detect domain + extract deep info
2. _generate_brief: create 1-paragraph story arc
3. _generate_scenes: expand brief into rich JSON scenes
4. _critique: self-evaluate (Gemini text)
5. _refine: regenerate if score < threshold (max 2 attempts)

Output: list[dict] — same format as legacy generate_script() for backwards compat.
"""
from __future__ import annotations
import json

from rich.console import Console

import config
from pipeline.agents.base_agent import (
    BaseAgent,
    CritiqueResult,
    call_gemini_with_retry,
    parse_json_response,
)
from pipeline.agents.sop_extractor import enrich_sop
from prompts.scenario_brief_prompt import BRIEF_PROMPT
from prompts.scenario_rich_prompt import RICH_SCENES_PROMPT
from prompts.scenario_critique_prompt import CRITIQUE_PROMPT
from prompts.script_prompt import _FORBIDDEN_WORDS, REQUIRED_ACTS

console = Console()


def _bullet_list(items: list[str], max_items: int = 8) -> str:
    """Format list as numbered bullets, truncated to max_items."""
    if not items:
        return "(정보 없음)"
    lines = [f"- {item}" for item in items[:max_items]]
    return "\n".join(lines)


class ScenarioAgent(BaseAgent):
    """Generate a rich scene list from SOP using plan-then-generate pattern."""

    name = "ScenarioAgent"

    def __init__(self, sop: dict, duration: int):
        self.sop = sop
        self.duration = duration
        self.brief: str = ""
        self._enriched = False

    # ─── Public entry ─────────────────────────────────────────────────────────

    def run_scenes(self) -> list[dict]:
        """Public method: returns list of scene dicts (legacy-compatible format)."""
        # Step 1: Enrich SOP with domain + deep_extract
        if not self._enriched:
            enrich_sop(self.sop)
            self._enriched = True

        # Step 2: Generate story brief (cached on self.brief)
        self.brief = self._generate_brief()
        console.print(f"[dim]Story brief generated ({len(self.brief)} chars)[/dim]")

        # Step 3-5: BaseAgent's run() handles generate/critique/refine loop
        scenes, critique = self.run(input_data=None)
        console.print(f"[dim]Scenario complete: score {critique.score:.1f}/10[/dim]")
        return scenes

    # ─── Brief generation ─────────────────────────────────────────────────────

    def _generate_brief(self) -> str:
        deep = self.sop.get("deep_extract") or {}
        prompt = BRIEF_PROMPT.format(
            duration=self.duration,
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
        return text.strip()

    # ─── BaseAgent overrides ──────────────────────────────────────────────────

    def _generate(self, input_data) -> list[dict]:
        """Generate rich scenes JSON from brief + deep extract."""
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
            brief=self.brief,
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

        # Gemini eval
        scenes_summary = "\n".join(
            f"[{s.get('scene_id')}] {s.get('act')}: \"{s.get('narration_ko', '')[:80]}\""
            for s in scenes
        )
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
            # Forbidden words = critical violation, always fail
            if has_forbidden:
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
            brief=self.brief,
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


def generate_script_v2(sop: dict, duration: int) -> list[dict]:
    """Drop-in replacement for pipeline.script_gen.generate_script using ScenarioAgent."""
    agent = ScenarioAgent(sop, duration)
    return agent.run_scenes()
