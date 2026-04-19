from __future__ import annotations
from pathlib import Path

import replicate
from rich.console import Console

import config
from models.scene_manifest import SceneManifest, SceneStatus

console = Console()


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
            console.print(f"[dim]Skip {scene.scene_id} — already at {scene.status}[/dim]")
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
            out_path.write_bytes(output[0].read())
            return True
        except Exception as exc:
            if attempt == config.MAX_RETRY:
                console.print(f"[red]Image gen error: {exc}[/red]")
                return False
    return False
