"""Auto-evaluation script: score each scene in a completed video using Gemini Vision.

Usage:
    uv run scripts/evaluate_video.py <video.mp4> <workspace_dir>

Outputs:
    output/<video_basename>_eval.json
    output/<video_basename>_eval.md
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import base64
from google import genai
from google.genai import types

import config
from models.scene_manifest import SceneManifest

_EVAL_PROMPT = """\
당신은 산업 안전교육 영상의 시각 품질 평가자입니다.
이 프레임은 "{equipment_type}" 장비 관련 안전교육 영상의 "{act}" 씬입니다.
씬 설명: {image_prompt}

다음 5개 항목을 0~10점으로 채점하고 JSON으로만 출력하세요 (다른 텍스트 없이):
{{
  "equipment_match": <0-10>,
  "character_consistency": <0-10>,
  "accident_realism": <0-10>,
  "composition": <0-10>,
  "subtitle_legibility": <0-10>,
  "reasons": {{<항목명>: "<7점 미만이면 한 문장 사유, 아니면 null>"}}
}}

채점 기준:
- equipment_match: 프레임 속 장비가 "{equipment_type}"과 일치하는지 (다른 장비 -5점)
- character_consistency: 작업자 복장/외모가 일관된지 (분할화면 -5점)
- accident_realism: consequence 씬에서 폭발/파편/콜라주 없이 현실적 위험 표현인지 (비해당 씬은 10점)
- composition: 단일 카메라 구도, 흐림 없음, 분할화면 없음
- subtitle_legibility: on_screen_text가 "{on_screen_text}"일 때 화면에 표시되어 있는지 (텍스트 없으면 10점)
"""


def _extract_frame(video_path: Path, timestamp_sec: float, out_path: Path) -> bool:
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(timestamp_sec),
                "-i", str(video_path),
                "-vframes", "1",
                "-q:v", "2",
                str(out_path),
            ],
            check=True,
            capture_output=True,
        )
        return out_path.exists() and out_path.stat().st_size > 0
    except Exception:
        return False


def _eval_frame(client: genai.Client, frame_path: Path, scene_meta: dict) -> dict:
    with open(frame_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    prompt = _EVAL_PROMPT.format(
        equipment_type=scene_meta.get("equipment_type") or "알 수 없음",
        act=scene_meta.get("act", ""),
        image_prompt=scene_meta.get("image_prompt", ""),
        on_screen_text=scene_meta.get("on_screen_text") or "",
    )

    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=[
            types.Part.from_bytes(data=base64.b64decode(img_b64), mime_type="image/jpeg"),
            prompt,
        ],
    )

    text = response.text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def evaluate(video_path: Path, workspace: Path, output_dir: Path) -> Path:
    manifest_path = workspace / "manifest.json"
    if not manifest_path.exists():
        print(f"[ERROR] manifest.json not found in {workspace}", file=sys.stderr)
        sys.exit(1)

    manifest = SceneManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    equipment_type = ""
    sop_json_path = workspace / "sop.json"
    if sop_json_path.exists():
        sop = json.loads(sop_json_path.read_text(encoding="utf-8"))
        equipment_type = sop.get("equipment_type") or ""

    client = genai.Client(api_key=config.GEMINI_API_KEY)

    results = []
    elapsed = 0.0

    with tempfile.TemporaryDirectory() as tmpdir:
        for scene in manifest.scenes:
            mid_ts = elapsed + scene.duration_sec / 2
            frame_path = Path(tmpdir) / f"{scene.scene_id}.jpg"

            print(f"  Evaluating {scene.scene_id} at {mid_ts:.1f}s...")
            if not _extract_frame(video_path, mid_ts, frame_path):
                print(f"  [WARN] Frame extraction failed for {scene.scene_id}, skipping")
                elapsed += scene.duration_sec
                continue

            try:
                scores = _eval_frame(client, frame_path, {
                    "equipment_type": equipment_type,
                    "act": scene.act,
                    "image_prompt": scene.image_prompt,
                    "on_screen_text": scene.on_screen_text,
                })
            except Exception as exc:
                print(f"  [WARN] Gemini eval failed for {scene.scene_id}: {exc}")
                elapsed += scene.duration_sec
                continue

            metric_keys = ["equipment_match", "character_consistency", "accident_realism",
                           "composition", "subtitle_legibility"]
            avg = sum(scores.get(k, 0) for k in metric_keys) / len(metric_keys)
            results.append({
                "scene_id": scene.scene_id,
                "act": scene.act,
                "timestamp": mid_ts,
                "scores": scores,
                "avg": round(avg, 2),
            })
            elapsed += scene.duration_sec

    if not results:
        print("[ERROR] No scenes evaluated.", file=sys.stderr)
        sys.exit(1)

    overall = sum(r["avg"] for r in results) / len(results)
    report = {"overall": round(overall, 2), "scenes": results}

    output_dir.mkdir(parents=True, exist_ok=True)
    stem = video_path.stem
    json_out = output_dir / f"{stem}_eval.json"
    md_out = output_dir / f"{stem}_eval.md"

    json_out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        f"# 영상 품질 평가 — {stem}",
        f"\n**종합 점수: {overall:.2f} / 10**\n",
        "| 씬 | 액트 | 장비 | 캐릭터 | 사고표현 | 구도 | 자막 | 평균 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        s = r["scores"]
        lines.append(
            f"| {r['scene_id']} | {r['act']} "
            f"| {s.get('equipment_match','?')} "
            f"| {s.get('character_consistency','?')} "
            f"| {s.get('accident_realism','?')} "
            f"| {s.get('composition','?')} "
            f"| {s.get('subtitle_legibility','?')} "
            f"| **{r['avg']}** |"
        )

    weak = [r for r in results if r["avg"] < 7]
    if weak:
        lines.append("\n## 개선 필요 씬\n")
        for r in weak:
            reasons = r["scores"].get("reasons", {})
            for k, v in reasons.items():
                if v:
                    lines.append(f"- **{r['scene_id']} / {k}**: {v}")

    md_out.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n종합 점수: {overall:.2f}/10")
    print(f"JSON: {json_out}")
    print(f"리포트: {md_out}")
    return json_out


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate safety training video quality")
    parser.add_argument("video", help="Path to output .mp4 file")
    parser.add_argument("workspace", help="Path to workspace directory (contains manifest.json)")
    parser.add_argument("--output-dir", default="./output", help="Directory for eval reports")
    args = parser.parse_args()

    video_path = Path(args.video)
    workspace = Path(args.workspace)
    output_dir = Path(args.output_dir)

    if not video_path.exists():
        print(f"[ERROR] Video not found: {video_path}", file=sys.stderr)
        sys.exit(1)
    if not workspace.exists():
        print(f"[ERROR] Workspace not found: {workspace}", file=sys.stderr)
        sys.exit(1)

    evaluate(video_path, workspace, output_dir)


if __name__ == "__main__":
    main()
