from __future__ import annotations
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from rich.console import Console

from models.scene_manifest import SceneManifest, SceneStatus
from pipeline.tts import _audio_duration

console = Console()

_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class AssemblyError(Exception):
    pass


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

    for scene in assemblable:
        if scene.status != SceneStatus.clip_ready:
            continue
        clip_path = clips_dir / f"{scene.scene_id}.mp4"
        audio_path = audio_dir / f"{scene.scene_id}.mp3"
        if not clip_path.exists():
            raise AssemblyError(f"missing clip: {clip_path}")
        if not audio_path.exists():
            raise AssemblyError(f"missing audio: {audio_path}")

    for scene in assemblable:
        merged_path = tmp_dir / f"{scene.scene_id}_merged.mp4"
        if merged_path.exists():
            continue

        clip_path = clips_dir / f"{scene.scene_id}.mp4"
        audio_path = audio_dir / f"{scene.scene_id}.mp3"
        norm_path = tmp_dir / f"{scene.scene_id}_norm.mp4"

        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(clip_path),
                "-vf", "scale=1920:1080",
                "-r", "24",
                "-c:v", "libx264", "-preset", "fast",
                str(norm_path),
            ],
            check=True, capture_output=True,
        )
        audio_dur = _audio_duration(audio_path)
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(norm_path),
                "-i", str(audio_path),
                "-t", str(audio_dur),
                "-c:v", "copy", "-c:a", "aac",
                str(merged_path),
            ],
            check=True, capture_output=True,
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

    output_path = _final_output_path(manifest.sop_title, output_dir)
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            str(output_path),
        ],
        check=True, capture_output=True,
    )

    for scene in assemblable:
        scene.status = SceneStatus.assembled
    manifest.save(workspace)

    console.print(f"[green]Output: {output_path}[/green]")
    return output_path


def _final_output_path(sop_title: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    # Whitelist: alphanumerics, underscore, hyphen, Korean syllables.
    safe_title = re.sub(r"[^A-Za-z0-9_\-\uAC00-\uD7A3]", "_", sop_title)[:40].strip("._-") or "untitled"
    if safe_title.upper() in _WINDOWS_RESERVED:
        safe_title = f"_{safe_title}"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = (output_dir / f"{safe_title}_{timestamp}.mp4").resolve()
    output_root = output_dir.resolve()
    if output_root not in candidate.parents:
        raise AssemblyError(f"output path escapes output_dir: {candidate}")
    return candidate
