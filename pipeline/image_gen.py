from __future__ import annotations
import re
import shutil
import time
from pathlib import Path

import replicate
from rich.console import Console

import config
from models.scene_manifest import SceneManifest, SceneStatus

console = Console()

THROTTLE_MAX_RETRIES = 5
_RESET_RE = re.compile(r"resets in\s*~?(\d+)s")
_SUBSCENE_RE = re.compile(r"^(S\d+)[a-z]$")  # matches S02a, S03b → parent group S02


def _throttle_sleep_seconds(exc: Exception) -> int | None:
    msg = str(exc)
    if "429" not in msg and "throttled" not in msg.lower():
        return None
    match = _RESET_RE.search(msg)
    return (int(match.group(1)) + 1) if match else 10


def generate_images(manifest: SceneManifest, workspace: Path) -> SceneManifest:
    images_dir = workspace / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    base_model = (
        "black-forest-labs/flux-dev"
        if config.USE_FLUX_DEV
        else config.DEFAULT_IMAGE_MODEL
    )
    ref_model = config.REF_IMAGE_MODEL

    # Track first-generated image per parent group for sub-scene reuse
    parent_images: dict[str, Path] = {}

    # Reference image: first eligible scene's PNG, used for character consistency
    ref_path: Path | None = None
    ref_path_candidate = images_dir / "_reference.png"
    if ref_path_candidate.exists():
        ref_path = ref_path_candidate

    is_first_scene = ref_path is None

    for scene in manifest.scenes:
        if scene.status == SceneStatus.skipped:
            continue
        if scene.status in (SceneStatus.image_ready, SceneStatus.clip_ready,
                             SceneStatus.merged_ready, SceneStatus.assembled):
            console.print(f"[dim]Skip {scene.scene_id} — already at {scene.status}[/dim]")
            out_path = images_dir / f"{scene.scene_id}.png"
            if out_path.exists():
                m = _SUBSCENE_RE.match(scene.scene_id)
                prefix = m.group(1) if m else scene.scene_id
                parent_images.setdefault(prefix, out_path)
            if ref_path is None and out_path.exists():
                ref_path = out_path
                is_first_scene = False
            continue

        out_path = images_dir / f"{scene.scene_id}.png"

        # Sub-scene: reuse first sub-scene's image (no extra FLUX call)
        m = _SUBSCENE_RE.match(scene.scene_id)
        if m:
            prefix = m.group(1)
            if prefix in parent_images:
                console.print(f"[dim]Reuse {parent_images[prefix].name} for sub-scene {scene.scene_id}[/dim]")
                shutil.copy2(parent_images[prefix], out_path)
                scene.status = SceneStatus.image_ready
                manifest.save(workspace)
                continue

        if is_first_scene:
            # Generate reference image with base model (fast), save as _reference.png + scene PNG
            console.print(f"[dim]Generating reference image for {scene.scene_id} ({base_model})[/dim]")
            success = _generate_with_retry(scene.image_prompt, ref_path_candidate, base_model)
            if success:
                ref_path = ref_path_candidate
                shutil.copy2(ref_path, out_path)
                is_first_scene = False
            else:
                success = False
        else:
            # Use reference model with reference image for character/equipment consistency
            console.print(f"[dim]Generating {scene.scene_id} with reference ({ref_model})[/dim]")
            success = _generate_ref_with_retry(scene.image_prompt, ref_path, out_path, ref_model)
            if not success:
                # Fallback to base model without reference
                console.print(f"[yellow]Ref model failed for {scene.scene_id}, falling back to {base_model}[/yellow]")
                success = _generate_with_retry(scene.image_prompt, out_path, base_model)

        if success:
            scene.status = SceneStatus.image_ready
            if m:
                parent_images.setdefault(m.group(1), out_path)
            else:
                parent_images.setdefault(scene.scene_id, out_path)
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


def _generate_ref_with_retry(prompt: str, ref_path: Path, out_path: Path, model: str) -> bool:
    """Generate image using flux-1.1-pro with a reference image for consistency."""
    throttle_retries = 0
    for attempt in range(config.MAX_RETRY + 1):
        try:
            with open(ref_path, "rb") as ref_file:
                output = replicate.run(
                    model,
                    input={
                        "prompt": prompt,
                        "aspect_ratio": "16:9",
                        "output_format": "png",
                        "image_prompt": ref_file,
                        "image_prompt_strength": 0.15,
                    },
                )
            # flux-1.1-pro returns a single FileOutput, not a list
            data = output.read() if hasattr(output, "read") else output[0].read()
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
                console.print(f"[red]Ref image gen error: {exc}[/red]")
                return False
    return False
