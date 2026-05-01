"""Stage-by-stage pipeline validator.

Validates intermediate outputs at each stage using Gemini (text) and
Gemini Vision (images/frames), so bad scenarios are caught before spending
money on FLUX ($0.04/image) and Kling ($0.50/clip).

Usage (standalone):
    uv run scripts/validate_stage.py --stage 3 --workspace workspace/<run_id>
    uv run scripts/validate_stage.py --stage 4 --workspace workspace/<run_id>
    uv run scripts/validate_stage.py --stage 5 --workspace workspace/<run_id>

Exit code: 0 = passed, 1 = failed (overall < threshold)
"""
from __future__ import annotations
import argparse
import base64
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from google import genai
from google.genai import types
from rich.console import Console
from rich.table import Table

import config
from models.scene_manifest import SceneManifest, SceneStatus
from prompts.script_prompt import _FORBIDDEN_WORDS, REQUIRED_ACTS

console = Console()

PASS_THRESHOLD = 7.0

# ─── Prompts ──────────────────────────────────────────────────────────────────

_STAGE3_PROMPT = """\
당신은 산업 안전교육 영상 시나리오 품질 평가자입니다.
아래는 "{equipment_type}" 장비 관련 30~180초 안전교육 영상 시나리오입니다.

씬 목록 (JSON):
{scenes_json}

다음 4개 항목을 0~10으로 채점하고 JSON으로만 출력하세요 (다른 텍스트 없이):
{{
  "act_coverage": <0-10>,
  "narration_quality": <0-10>,
  "equipment_lock": <0-10>,
  "scene_coherence": <0-10>,
  "issues": ["문제점이 있으면 한 문장씩, 없으면 빈 배열"]
}}

채점 기준:
- act_coverage: hook/conflict/consequence/resolution/rules 5개 모두 있으면 10점. 1개 누락당 -2점.
- narration_quality: 한국어가 자연스럽고 안전 메시지가 명확한가 (0=번역투/어색, 10=자연스럽고 명확)
- equipment_lock: 모든 씬에서 "{equipment_type}"이 일관되게 등장하는가 (다른 장비 묘사 있으면 -3점/건)
- scene_coherence: hook→conflict→consequence→resolution→rules 흐름이 논리적인가
"""

_STAGE4_PROMPT = """\
당신은 산업 안전교육 영상의 이미지 품질 평가자입니다.
이 이미지는 "{equipment_type}" 장비 관련 안전교육 영상의 "{act}" 씬입니다.
씬 설명: {image_prompt}

다음 4개 항목을 0~10으로 채점하고 JSON으로만 출력하세요 (다른 텍스트 없이):
{{
  "equipment_match": <0-10>,
  "no_split_screen": <0-10>,
  "character_ok": <0-10>,
  "composition": <0-10>,
  "reason": "<7점 미만 항목이 있으면 한 문장, 없으면 null>"
}}

채점 기준:
- equipment_match: 이미지에 "{equipment_type}"이 있는가 (다른 장비면 2점 이하)
- no_split_screen: 분할화면/콜라주/사이드바이사이드 없음 (있으면 0점)
- character_ok: 작업자가 안전모·안전조끼 등 보호장비 착용 여부
- composition: 단일 카메라 구도, 흐림 없음, 현실적 장면
"""

_STAGE5_PROMPT = """\
당신은 산업 안전교육 영상의 영상 품질 평가자입니다.
이 프레임은 "{equipment_type}" 장비 관련 안전교육 영상의 "{act}" 씬에서 추출한 중간 프레임입니다.
씬 설명: {image_prompt}  |  모션 지시: {motion_prompt}

다음 4개 항목을 0~10으로 채점하고 JSON으로만 출력하세요 (다른 텍스트 없이):
{{
  "equipment_match": <0-10>,
  "no_split_screen": <0-10>,
  "motion_natural": <0-10>,
  "character_ok": <0-10>,
  "reason": "<7점 미만 항목이 있으면 한 문장, 없으면 null>"
}}

채점 기준:
- equipment_match: 프레임에 "{equipment_type}"이 있는가
- no_split_screen: 분할화면/콜라주 없음 (있으면 0점)
- motion_natural: 모션이 지시에 맞게 자연스럽게 표현됐는가
- character_ok: 작업자가 안전장비 착용
"""


# ─── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class SceneScore:
    scene_id: str
    act: str
    scores: dict
    avg: float
    issues: list[str] = field(default_factory=list)


@dataclass
class StageResult:
    stage: int
    overall: float
    passed: bool
    scene_scores: list[SceneScore]
    summary: str
    deterministic_issues: list[str] = field(default_factory=list)


# ─── Shared helpers ───────────────────────────────────────────────────────────

def _gemini_client() -> genai.Client:
    return genai.Client(api_key=config.GEMINI_API_KEY)


def _parse_json_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _extract_mid_frame(clip_path: Path, out_path: Path) -> bool:
    try:
        # Get duration
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(clip_path)],
            capture_output=True, text=True, check=True,
        )
        duration = float(r.stdout.strip())
        mid = duration / 2
        subprocess.run(
            ["ffmpeg", "-y", "-ss", str(mid), "-i", str(clip_path),
             "-vframes", "1", "-q:v", "2", str(out_path)],
            check=True, capture_output=True,
        )
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception as exc:
        console.print(f"[dim]Frame extract failed for {clip_path.name}: {exc}[/dim]")
        return False


def _score_avg(scores: dict, exclude: set | None = None) -> float:
    exclude = exclude or {"reason", "issues"}
    vals = [v for k, v in scores.items() if k not in exclude and isinstance(v, (int, float))]
    return round(sum(vals) / len(vals), 2) if vals else 0.0


# ─── Stage 3: Scenario / manifest ────────────────────────────────────────────

def _deterministic_stage3(manifest: SceneManifest, equipment_type: str) -> list[str]:
    issues = []
    acts = {s.act for s in manifest.scenes}
    missing = REQUIRED_ACTS - acts
    if missing:
        issues.append(f"누락된 액트: {', '.join(sorted(missing))}")
    for scene in manifest.scenes:
        prompt_lower = scene.image_prompt.lower()
        for word in _FORBIDDEN_WORDS:
            if word in prompt_lower:
                issues.append(f"{scene.scene_id}: 금지어 '{word}' in image_prompt")
    if equipment_type:
        eq_lower = equipment_type.lower().split()[0]
        for scene in manifest.scenes:
            if eq_lower not in scene.image_prompt.lower():
                issues.append(f"{scene.scene_id}: equipment_type '{eq_lower}' not in image_prompt")
    return issues


def validate_stage3(workspace: Path) -> StageResult:
    manifest_path = workspace / "manifest.json"
    sop_path = workspace / "sop.json"
    if not manifest_path.exists():
        return StageResult(3, 0.0, False, [], "manifest.json 없음")

    manifest = SceneManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    equipment_type = ""
    if sop_path.exists():
        sop = json.loads(sop_path.read_text(encoding="utf-8"))
        equipment_type = sop.get("equipment_type") or ""

    det_issues = _deterministic_stage3(manifest, equipment_type)
    det_penalty = min(len(det_issues) * 1.5, 5.0)

    # Gemini qualitative assessment (single call for full manifest)
    client = _gemini_client()
    scenes_json = json.dumps(
        [{"scene_id": s.scene_id, "act": s.act, "narration_ko": s.narration_ko,
          "image_prompt": s.image_prompt, "on_screen_text": s.on_screen_text}
         for s in manifest.scenes],
        ensure_ascii=False, indent=2,
    )
    prompt = _STAGE3_PROMPT.format(
        equipment_type=equipment_type or "해당 SOP의 주요 장비",
        scenes_json=scenes_json,
    )
    try:
        response = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=prompt,
        )
        result = _parse_json_response(response.text)
        llm_issues = result.pop("issues", [])
        llm_avg = _score_avg(result)
        overall = max(0.0, round(llm_avg - det_penalty, 2))
        all_issues = det_issues + (llm_issues if isinstance(llm_issues, list) else [])
        scene_score = SceneScore(
            scene_id="manifest",
            act="all",
            scores=result,
            avg=llm_avg,
            issues=llm_issues if isinstance(llm_issues, list) else [],
        )
    except Exception as exc:
        console.print(f"[yellow]Gemini stage3 eval failed: {exc}[/yellow]")
        score = max(0.0, 10.0 - det_penalty)
        overall = round(score, 2)
        all_issues = det_issues
        scene_score = SceneScore("manifest", "all", {}, overall)

    passed = overall >= PASS_THRESHOLD
    summary = f"Overall {overall:.1f}/10 ({'PASS' if passed else 'FAIL'})"
    return StageResult(
        stage=3, overall=overall, passed=passed,
        scene_scores=[scene_score], summary=summary,
        deterministic_issues=det_issues,
    )


# ─── Stage 4: Images ──────────────────────────────────────────────────────────

def validate_stage4(workspace: Path) -> StageResult:
    manifest_path = workspace / "manifest.json"
    images_dir = workspace / "images"
    sop_path = workspace / "sop.json"
    if not manifest_path.exists():
        return StageResult(4, 0.0, False, [], "manifest.json 없음")

    manifest = SceneManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    equipment_type = ""
    if sop_path.exists():
        sop = json.loads(sop_path.read_text(encoding="utf-8"))
        equipment_type = sop.get("equipment_type") or ""

    client = _gemini_client()
    scene_scores: list[SceneScore] = []

    for scene in manifest.scenes:
        if scene.status == SceneStatus.skipped:
            continue
        img_path = images_dir / f"{scene.scene_id}.png"
        if not img_path.exists():
            continue

        prompt = _STAGE4_PROMPT.format(
            equipment_type=equipment_type or "해당 SOP의 주요 장비",
            act=scene.act,
            image_prompt=scene.image_prompt,
        )
        try:
            with open(img_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()
            response = client.models.generate_content(
                model=config.GEMINI_MODEL,
                contents=[
                    types.Part.from_bytes(data=base64.b64decode(img_b64), mime_type="image/png"),
                    prompt,
                ],
            )
            result = _parse_json_response(response.text)
            reason = result.pop("reason", None)
            avg = _score_avg(result)
            issues = [reason] if reason and avg < 7 else []
            scene_scores.append(SceneScore(scene.scene_id, scene.act, result, avg, issues))
        except Exception as exc:
            console.print(f"[yellow]Stage4 eval failed for {scene.scene_id}: {exc}[/yellow]")
            scene_scores.append(SceneScore(scene.scene_id, scene.act, {}, 0.0, [str(exc)]))

    if not scene_scores:
        return StageResult(4, 0.0, False, [], "평가 가능한 이미지 없음")

    overall = round(sum(s.avg for s in scene_scores) / len(scene_scores), 2)
    passed = overall >= PASS_THRESHOLD
    summary = f"Overall {overall:.1f}/10 ({len(scene_scores)} scenes, {'PASS' if passed else 'FAIL'})"
    return StageResult(stage=4, overall=overall, passed=passed, scene_scores=scene_scores, summary=summary)


# ─── Stage 5: Video clips ─────────────────────────────────────────────────────

def validate_stage5(workspace: Path) -> StageResult:
    manifest_path = workspace / "manifest.json"
    clips_dir = workspace / "clips"
    sop_path = workspace / "sop.json"
    if not manifest_path.exists():
        return StageResult(5, 0.0, False, [], "manifest.json 없음")

    manifest = SceneManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    equipment_type = ""
    if sop_path.exists():
        sop = json.loads(sop_path.read_text(encoding="utf-8"))
        equipment_type = sop.get("equipment_type") or ""

    client = _gemini_client()
    scene_scores: list[SceneScore] = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for scene in manifest.scenes:
            if scene.status not in (SceneStatus.clip_ready, SceneStatus.merged_ready, SceneStatus.assembled):
                continue
            clip_path = clips_dir / f"{scene.scene_id}.mp4"
            if not clip_path.exists():
                continue

            frame_path = Path(tmpdir) / f"{scene.scene_id}.jpg"
            if not _extract_mid_frame(clip_path, frame_path):
                continue

            prompt = _STAGE5_PROMPT.format(
                equipment_type=equipment_type or "해당 SOP의 주요 장비",
                act=scene.act,
                image_prompt=scene.image_prompt,
                motion_prompt=scene.motion_prompt,
            )
            try:
                with open(frame_path, "rb") as f:
                    img_b64 = base64.b64encode(f.read()).decode()
                response = client.models.generate_content(
                    model=config.GEMINI_MODEL,
                    contents=[
                        types.Part.from_bytes(data=base64.b64decode(img_b64), mime_type="image/jpeg"),
                        prompt,
                    ],
                )
                result = _parse_json_response(response.text)
                reason = result.pop("reason", None)
                avg = _score_avg(result)
                issues = [reason] if reason and avg < 7 else []
                scene_scores.append(SceneScore(scene.scene_id, scene.act, result, avg, issues))
            except Exception as exc:
                console.print(f"[yellow]Stage5 eval failed for {scene.scene_id}: {exc}[/yellow]")
                scene_scores.append(SceneScore(scene.scene_id, scene.act, {}, 0.0, [str(exc)]))

    if not scene_scores:
        return StageResult(5, 0.0, False, [], "평가 가능한 클립 없음")

    overall = round(sum(s.avg for s in scene_scores) / len(scene_scores), 2)
    passed = overall >= PASS_THRESHOLD
    summary = f"Overall {overall:.1f}/10 ({len(scene_scores)} clips, {'PASS' if passed else 'FAIL'})"
    return StageResult(stage=5, overall=overall, passed=passed, scene_scores=scene_scores, summary=summary)


# ─── Console output ───────────────────────────────────────────────────────────

def _score_color(score: float) -> str:
    if score >= 8:
        return "green"
    if score >= PASS_THRESHOLD:
        return "yellow"
    return "red"


def print_result(result: StageResult) -> None:
    stage_labels = {3: "Stage 3: 시나리오", 4: "Stage 4: 이미지", 5: "Stage 5: 영상"}
    label = stage_labels.get(result.stage, f"Stage {result.stage}")
    color = _score_color(result.overall)
    verdict = "✓ PASS" if result.passed else "✗ FAIL"

    console.rule(f"[bold]{label} 검증 결과[/bold]")
    console.print(f"[bold {color}]{verdict}  {result.overall:.1f}/10[/bold {color}]  (기준: {PASS_THRESHOLD})")

    if result.deterministic_issues:
        console.print("\n[red]규칙 위반:[/red]")
        for issue in result.deterministic_issues:
            console.print(f"  • {issue}")

    if result.stage == 3 and result.scene_scores:
        s = result.scene_scores[0]
        if s.scores:
            console.print("\n[dim]Gemini 세부 점수:[/dim]")
            for k, v in s.scores.items():
                if isinstance(v, (int, float)):
                    c = _score_color(float(v))
                    console.print(f"  {k:<22} [{c}]{v:.0f}/10[/{c}]")
        if s.issues:
            console.print("\n[yellow]지적 사항:[/yellow]")
            for issue in s.issues:
                console.print(f"  • {issue}")
    else:
        # Per-scene table for stages 4/5
        table = Table(show_header=True, header_style="bold")
        table.add_column("씬", style="dim")
        table.add_column("액트")
        table.add_column("평균")

        metric_keys = [k for k in (result.scene_scores[0].scores if result.scene_scores else {})
                       if k not in ("reason", "issues")]
        for k in metric_keys:
            table.add_column(k[:12])

        for s in result.scene_scores:
            avg_str = f"[{_score_color(s.avg)}]{s.avg:.1f}[/{_score_color(s.avg)}]"
            row = [s.scene_id, s.act, avg_str]
            for k in metric_keys:
                v = s.scores.get(k, "-")
                if isinstance(v, (int, float)):
                    row.append(f"[{_score_color(float(v))}]{v:.0f}[/{_score_color(float(v))}]")
                else:
                    row.append(str(v))
            table.add_row(*row)

        console.print(table)

        weak = [s for s in result.scene_scores if s.issues]
        if weak:
            console.print("\n[yellow]개선 필요 씬:[/yellow]")
            for s in weak:
                for issue in s.issues:
                    console.print(f"  [{s.scene_id} / {s.act}] {issue}")


# ─── CLI entry point ──────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Validate pipeline stage output")
    parser.add_argument("--stage", type=int, required=True, choices=[3, 4, 5],
                        help="Stage number to validate (3=scenario, 4=images, 5=clips)")
    parser.add_argument("--workspace", required=True, help="Path to run workspace directory")
    args = parser.parse_args()

    workspace = Path(args.workspace)
    if not workspace.exists():
        console.print(f"[red]Workspace not found: {workspace}[/red]")
        sys.exit(1)

    validators = {3: validate_stage3, 4: validate_stage4, 5: validate_stage5}
    result = validators[args.stage](workspace)
    print_result(result)
    sys.exit(0 if result.passed else 1)


if __name__ == "__main__":
    main()
