from __future__ import annotations
import re
import time
from pathlib import Path

import replicate
from rich.console import Console

import config
from models.scene_manifest import SceneManifest, SceneStatus

console = Console()

THROTTLE_MAX_RETRIES = 5
_RESET_RE = re.compile(r"resets in\s*~?(\d+)s")


def _throttle_sleep_seconds(exc: Exception) -> int | None:
    msg = str(exc)
    if "429" not in msg and "throttled" not in msg.lower():
        return None
    match = _RESET_RE.search(msg)
    return (int(match.group(1)) + 1) if match else 10


def generate_images(manifest: SceneManifest, workspace: Path) -> SceneManifest:
    images_dir = workspace / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    model = (
        "black-forest-labs/flux-dev"
        if config.USE_FLUX_DEV
        else config.DEFAULT_IMAGE_MODEL
    )

    for scene in manifest.scenes:
        if scene.status == SceneStatus.skipped:
            continue
        if scene.status in (SceneStatus.image_ready, SceneStatus.clip_ready,
                             SceneStatus.merged_ready, SceneStatus.assembled):
            console.print(f"[dim]Skip {scene.scene_id} - already at {scene.status}[/dim]")
            continue

        out_path = images_dir / f"{scene.scene_id}.png"
        success = _generate_with_retry(scene.image_prompt, out_path, model)
        if success:
            scene.status = SceneStatus.image_ready
        else:
            scene.status = SceneStatus.skipped
            console.print(f"[yellow]Warning: image gen failed for {scene.scene_id}, skipping[/yellow]")

        manifest.save(workspace)

    return manifest


def _generate_with_retry(prompt: str, out_path: Path, model: str) -> bool:
    throttle_retries = 0
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
            data = output[0].read()
            if not data:
                raise ValueError(f"empty image response from {model}")
            out_path.write_bytes(data)
            return True
        except Exception as exc:
            sleep_s = _throttle_sleep_seconds(exc)
            if sleep_s is not None and throttle_retries < THROTTLE_MAX_RETRIES:
                throttle_retries += 1
                console.print(f"[dim]429 throttled - sleeping {sleep_s}s (retry {throttle_retries}/{THROTTLE_MAX_RETRIES})[/dim]")
                time.sleep(sleep_s)
                continue
            if attempt == config.MAX_RETRY:
                console.print(f"[red]Image gen error: {exc}[/red]")
                return False
    return False
