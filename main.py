from __future__ import annotations
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console

import config
from models.scene_manifest import SceneManifest, SceneStatus
from pipeline.assembler import assemble, AssemblyError
from pipeline.image_gen import generate_images
from pipeline.scene_splitter import split_scenes
from pipeline.script_gen import generate_script
from pipeline.sop_parser import parse_sop, ParseError
from pipeline.tts import synthesize
from pipeline.video_gen import generate_videos
from scripts.evaluate_video import evaluate as evaluate_video
from scripts.validate_stage import (
    validate_stage3, validate_stage4, validate_stage5, print_result, PASS_THRESHOLD,
)

console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safety Training Video Auto-Generation Pipeline"
    )
    parser.add_argument("--sop", help="Path to SOP file (.docx or .pdf)")
    parser.add_argument(
        "--duration", type=int, default=config.DEFAULT_DURATION,
        help="Target duration in seconds (30 or 180, default: 180)"
    )
    parser.add_argument(
        "--stage", help="Stage range to run, e.g. '4-5' or '3'"
    )
    parser.add_argument(
        "--run-id", dest="run_id",
        help="Workspace run_id to resume (required with --stage, auto-detected if omitted)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show manifest without generating media"
    )
    parser.add_argument(
        "--evaluate", action="store_true",
        help="Run auto-evaluation on the assembled video after Stage 7"
    )
    parser.add_argument(
        "--validate", action="store_true",
        help="Auto-validate output after stages 3, 4, 5 using Gemini; abort if score < 7"
    )
    return parser


def parse_stage_range(stage_str: str) -> tuple[int, int]:
    parts = stage_str.split("-")
    if len(parts) == 1:
        s = int(parts[0])
        start = end = s
    elif len(parts) == 2:
        start, end = int(parts[0]), int(parts[1])
    else:
        raise ValueError(f"Invalid --stage format: {stage_str}")
    if not (1 <= start <= 7 and 1 <= end <= 7 and start <= end):
        raise ValueError(f"Invalid --stage range: {stage_str} (valid: 1-7)")
    return start, end


def _resolve_run_id(run_id: str | None) -> str:
    if run_id:
        return run_id
    workspace = config.WORKSPACE_DIR
    if not workspace.exists():
        console.print("[red]No workspace found. Provide --run-id or run from Stage 1.[/red]")
        sys.exit(1)
    runs = sorted(workspace.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    runs = [r for r in runs if r.is_dir()]
    if not runs:
        console.print("[red]No existing workspace run found.[/red]")
        sys.exit(1)
    latest = runs[0].name
    answer = input(f"Use latest run '{latest}'? [y/N] ").strip().lower()
    if answer != "y":
        sys.exit("Aborted.")
    return latest


def _load_manifest(workspace: Path) -> SceneManifest:
    manifest_path = workspace / "manifest.json"
    if not manifest_path.exists():
        console.print(f"[red]manifest.json not found in {workspace}[/red]")
        sys.exit(1)
    return SceneManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.stage:
        start, end = parse_stage_range(args.stage)
        run_id = _resolve_run_id(args.run_id)
        workspace = config.WORKSPACE_DIR / run_id
        manifest = _load_manifest(workspace)
        _run_stages(start, end, manifest=manifest, workspace=workspace, args=args)
        return

    if not args.sop:
        parser.error("--sop is required when not using --stage")

    sop_path = Path(args.sop)
    if not sop_path.exists():
        console.print(f"[red]SOP file not found: {sop_path}[/red]")
        sys.exit(1)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    workspace = config.WORKSPACE_DIR / run_id
    workspace.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    console.print(f"[bold green]Run ID: {run_id}[/bold green]")

    _run_stages(1, 7, sop_path=sop_path, workspace=workspace, args=args)


def _run_stages(
    start: int,
    end: int,
    workspace: Path,
    args: argparse.Namespace,
    sop_path: Path | None = None,
    manifest: SceneManifest | None = None,
) -> None:
    if start <= 1 <= end:
        if sop_path is None:
            console.print("[red]--sop is required when stage range includes 1[/red]")
            sys.exit(1)
        console.rule("[bold]Stage 1: SOP Parser[/bold]")
        sop = parse_sop(sop_path, run_workspace=workspace)
    else:
        sop_json_path = workspace / "sop.json"
        if not sop_json_path.exists():
            console.print(f"[red]sop.json not found in {workspace}. Run stage 1 first or provide --sop.[/red]")
            sys.exit(1)
        sop = json.loads(sop_json_path.read_text(encoding="utf-8"))

    script: list[dict] | None = None
    if start <= 2 <= end:
        console.rule("[bold]Stage 2: Script Generator[/bold]")
        script = generate_script(sop=sop, duration=args.duration)

    if start <= 3 <= end:
        console.rule("[bold]Stage 3: Scene Splitter (+ TTS)[/bold]")
        if script is None:
            raise ValueError("Stage 3 requires stage 2. Use --stage 2-3 or run stage 2 first.")
        manifest = split_scenes(
            script=script,
            workspace=workspace,
            video_style="shortform" if args.duration <= 30 else "hybrid",
            sop_title=sop["sop_title"],
            duration=args.duration,
            equipment_type=sop.get("equipment_type") or "",
        )
        if args.dry_run:
            console.print(manifest.model_dump_json(indent=2))
            return

        if getattr(args, "validate", False):
            result = validate_stage3(workspace)
            print_result(result)
            if not result.passed:
                _abort_or_continue(result.overall, 3)

    if manifest is None:
        manifest = _load_manifest(workspace)

    if start <= 4 <= end:
        console.rule("[bold]Stage 4: Image Generator[/bold]")
        manifest = generate_images(manifest=manifest, workspace=workspace)
        if getattr(args, "validate", False):
            result = validate_stage4(workspace)
            print_result(result)
            if not result.passed:
                _abort_or_continue(result.overall, 4)

    if start <= 5 <= end:
        console.rule("[bold]Stage 5: Video Generator[/bold]")
        manifest = generate_videos(manifest=manifest, workspace=workspace)
        if getattr(args, "validate", False):
            result = validate_stage5(workspace)
            print_result(result)
            if not result.passed:
                _abort_or_continue(result.overall, 5)

    if start <= 6 <= end:
        console.rule("[bold]Stage 6: TTS (fill gaps)[/bold]")
        _run_tts_stage(manifest, workspace)

    if start <= 7 <= end:
        console.rule("[bold]Stage 7: Assembler[/bold]")
        output_path = assemble(
            manifest=manifest,
            workspace=workspace,
            output_dir=config.OUTPUT_DIR,
        )
        console.print(f"\n[bold green]Done! Output: {output_path}[/bold green]")
        if args.evaluate:
            console.rule("[bold]Auto-Evaluation[/bold]")
            evaluate_video(output_path, workspace, config.OUTPUT_DIR)


def _abort_or_continue(score: float, stage: int) -> None:
    import os
    if os.environ.get("FORCE_RUN") == "1":
        return
    answer = input(
        f"\nStage {stage} score {score:.1f}/10 (기준 {PASS_THRESHOLD}). 계속 진행? [y/N] "
    ).strip().lower()
    if answer != "y":
        raise SystemExit(f"Aborted — Stage {stage} 점수 미달. --stage 2-{stage} 로 재실행하세요.")


_SUB_SCENE_RE = re.compile(r"^S\d+[a-z]$")


def _run_tts_stage(manifest: SceneManifest, workspace: Path) -> None:
    audio_dir = workspace / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for scene in manifest.scenes:
        if scene.status == SceneStatus.skipped:
            continue
        audio_path = audio_dir / f"{scene.scene_id}.wav"
        if audio_path.exists():
            console.print(f"[dim]Skip TTS {scene.scene_id} - already exists[/dim]")
            continue
        if _SUB_SCENE_RE.match(scene.scene_id):
            # Sub-scene audio is a slice of the parent's audio. Re-synthesizing
            # scene.narration_ko would produce the full parent narration and
            # break sub-scene timing. Rebuild requires re-running Stage 3.
            console.print(
                f"[yellow]Skip TTS {scene.scene_id} - sub-scene audio missing; "
                f"re-run stage 3 to regenerate from parent.[/yellow]"
            )
            continue
        synthesize(
            text=scene.narration_ko,
            provider=manifest.tts_provider or "google",
            voice=manifest.tts_voice or "ko-KR-Wavenet-B",
            output_path=audio_path,  # .wav
        )
        if scene.status not in (SceneStatus.clip_ready, SceneStatus.assembled):
            scene.status = SceneStatus.audio_ready
        (workspace / "manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
