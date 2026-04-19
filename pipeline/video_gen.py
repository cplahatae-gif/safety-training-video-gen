from __future__ import annotations
import os
from pathlib import Path

import replicate
from rich.console import Console

import config
from models.scene_manifest import SceneManifest, SceneStatus

console = Console()

COST_PER_SEC = 0.05
COST_WARN_THRESHOLD = 15.0


def generate_videos(manifest: SceneManifest, workspace: Path) -> SceneManifest:
    clips_dir = workspace / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    images_dir = workspace / "images"

    active_scenes = [s for s in manifest.scenes if s.status == SceneStatus.image_ready]
    total_sec = sum(s.duration_sec for s in active_scenes)
    estimated_cost = total_sec * COST_PER_SEC
    if estimated_cost > COST_WARN_THRESHOLD:
        console.print(
            f"[bold yellow]Warning: estimated Kling cost ${estimated_cost:.2f} (>{COST_WARN_THRESHOLD}).[/bold yellow]"
        )
        if os.environ.get("FORCE_RUN") != "1":
            answer = input("Continue? [y/N] ").strip().lower()
            if answer != "y":
                raise SystemExit("Aborted by user.")

    for scene in manifest.scenes:
        if scene.status != SceneStatus.image_ready:
            continue

        img_path = images_dir / f"{scene.scene_id}.png"
        clip_path = clips_dir / f"{scene.scene_id}.mp4"

        success = _generate_with_retry(scene, img_path, clip_path)

        if success:
            scene.status = SceneStatus.clip_ready
        else:
            scene.status = SceneStatus.skipped
            console.print(f"[yellow]Warning: video gen failed for {scene.scene_id}, skipping[/yellow]")

        manifest.save(workspace)

    return manifest


def _generate_with_retry(scene, img_path: Path, clip_path: Path) -> bool:
    duration = 10 if scene.duration_sec > 5 else 5
    for attempt in range(config.MAX_RETRY + 1):
        try:
            with open(img_path, "rb") as img_file:
                output = replicate.run(
                    config.DEFAULT_VIDEO_MODEL,
                    input={
                        "prompt": scene.motion_prompt,
                        "start_image": img_file,
                        "duration": duration,
                        "aspect_ratio": "16:9",
                        "negative_prompt": "blur, distort, low quality, watermark",
                    },
                )
            data = output.read()
            if not data:
                raise ValueError(f"empty video response from {config.DEFAULT_VIDEO_MODEL}")
            clip_path.write_bytes(data)
            return True
        except Exception as exc:
            if attempt == config.MAX_RETRY:
                console.print(f"[red]Video gen error: {exc}[/red]")
                return False
    return False
