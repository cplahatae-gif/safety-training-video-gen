from __future__ import annotations
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from rich.console import Console

import config
from models.scene_manifest import SceneManifest, SceneStatus
from pipeline.tts import _audio_duration

console = Console()

_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
_AUDIO_EXT = ".wav"  # TTS now outputs LINEAR16 WAV


class AssemblyError(Exception):
    pass


def _run_ffmpeg(cmd: list[str], stage: str) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        console.print(f"[red]ffmpeg {stage} failed (exit {exc.returncode}):[/red]\n{stderr}")
        raise AssemblyError(
            f"ffmpeg {stage} failed: {stderr.strip().splitlines()[-1] if stderr else 'no stderr'}"
        ) from exc


def _escape_drawtext(text: str) -> str:
    """Escape special characters for ffmpeg drawtext filter."""
    return (
        text
        .replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
    )


def _subtitle_vf(text: str, font_path: str) -> str:
    """Build drawtext video filter string for on-screen text."""
    escaped = _escape_drawtext(text)
    safe_font = font_path.replace("\\", "/").replace(":", "\\:")
    return (
        f"drawtext=fontfile='{safe_font}'"
        f":text='{escaped}'"
        f":fontsize=52"
        f":fontcolor=white"
        f":borderw=3"
        f":bordercolor=black@0.8"
        f":x=(w-text_w)/2"
        f":y=h-text_h-80"
    )


def assemble(manifest: SceneManifest, workspace: Path, output_dir: Path) -> Path:
    if not shutil.which("ffmpeg"):
        raise SystemExit(
            "FFmpeg not found. Install it:\n"
            "  Windows: winget install Gyan.FFmpeg\n"
            "  Mac:     brew install ffmpeg\n"
            "  Linux:   sudo apt install ffmpeg"
        )
    assemblable = [
        s for s in manifest.scenes
        if s.status in (SceneStatus.clip_ready, SceneStatus.merged_ready)
    ]

    if not assemblable:
        raise AssemblyError("No assemblable scenes — all scenes were skipped or pending.")

    clips_dir = workspace / "clips"
    audio_dir = workspace / "audio"
    tmp_dir = workspace / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Pre-assembly integrity check for clip_ready scenes
    for scene in assemblable:
        if scene.status != SceneStatus.clip_ready:
            continue
        clip_path = clips_dir / f"{scene.scene_id}.mp4"
        audio_path = audio_dir / f"{scene.scene_id}{_AUDIO_EXT}"
        if not clip_path.exists():
            raise AssemblyError(f"missing clip: {clip_path}")
        if not audio_path.exists():
            raise AssemblyError(f"missing audio: {audio_path}")

    subtitle_font = config.SUBTITLE_FONT_PATH

    for scene in assemblable:
        merged_path = tmp_dir / f"{scene.scene_id}_merged.mp4"
        if merged_path.exists() and merged_path.stat().st_size >= 1024:
            continue
        if merged_path.exists():
            merged_path.unlink()

        clip_path = clips_dir / f"{scene.scene_id}.mp4"
        audio_path = audio_dir / f"{scene.scene_id}{_AUDIO_EXT}"
        norm_path = tmp_dir / f"{scene.scene_id}_norm.mp4"

        # Step 1: Normalize + fade in/out
        dur = scene.duration_sec
        fade_out_start = max(0.0, dur - 0.2)
        vf_normalize = (
            f"scale=1920:1080,"
            f"fade=t=in:st=0:d=0.2,"
            f"fade=t=out:st={fade_out_start:.2f}:d=0.2"
        )
        _run_ffmpeg(
            [
                "ffmpeg", "-y", "-i", str(clip_path),
                "-vf", vf_normalize,
                "-r", "24",
                "-c:v", "libx264", "-preset", "fast",
                str(norm_path),
            ],
            stage=f"normalize {scene.scene_id}",
        )

        # Step 2: Merge video + audio (+ optional subtitle)
        audio_dur = _audio_duration(audio_path)

        vf_merge = "null"
        if scene.on_screen_text:
            vf_merge = _subtitle_vf(scene.on_screen_text, subtitle_font)

        _run_ffmpeg(
            [
                "ffmpeg", "-y",
                "-i", str(norm_path),
                "-i", str(audio_path),
                "-t", str(audio_dur),
                "-vf", vf_merge,
                "-c:v", "libx264", "-preset", "fast",
                "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
                str(merged_path),
            ],
            stage=f"merge {scene.scene_id}",
        )

        scene.status = SceneStatus.merged_ready
        manifest.save(workspace)

    merged_paths = [
        tmp_dir / f"{s.scene_id}_merged.mp4"
        for s in assemblable
    ]
    concat_list = tmp_dir / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in merged_paths),
        encoding="utf-8",
    )

    concat_path = tmp_dir / "_concat.mp4"
    _run_ffmpeg(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            str(concat_path),
        ],
        stage="concat",
    )

    output_path = _final_output_path(manifest.sop_title, output_dir)

    # Step 3: BGM mixing (optional)
    bgm = config.BGM_FILE
    if bgm and Path(bgm).exists():
        _run_ffmpeg(
            [
                "ffmpeg", "-y",
                "-i", str(concat_path),
                "-stream_loop", "-1", "-i", bgm,
                "-filter_complex",
                f"[1:a]volume={config.BGM_VOLUME_DB}dB[bgm];[0:a][bgm]amix=inputs=2:duration=first[a]",
                "-map", "0:v",
                "-map", "[a]",
                "-c:v", "copy",
                "-c:a", "aac", "-b:a", "192k",
                str(output_path),
            ],
            stage="bgm_mix",
        )
    else:
        concat_path.rename(output_path)

    for scene in assemblable:
        scene.status = SceneStatus.assembled
    manifest.save(workspace)

    console.print(f"[green]Output: {output_path}[/green]")
    return output_path


def _final_output_path(sop_title: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_title = re.sub(r"[^A-Za-z0-9_\-\uAC00-\uD7A3]", "_", sop_title)[:40].strip("._-") or "untitled"
    if safe_title.upper() in _WINDOWS_RESERVED:
        safe_title = f"_{safe_title}"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = (output_dir / f"{safe_title}_{timestamp}.mp4").resolve()
    output_root = output_dir.resolve()
    if output_root not in candidate.parents:
        raise AssemblyError(f"output path escapes output_dir: {candidate}")
    return candidate
