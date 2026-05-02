from __future__ import annotations
import json
import math
import subprocess
from pathlib import Path

from rich.console import Console

from models.scene_manifest import Scene, SceneManifest, SceneStatus
from pipeline.tts import synthesize
from prompts.scene_prompt import build_image_prompt

console = Console()

DEFAULT_PROVIDER = "google"
DEFAULT_VOICE = "ko-KR-Wavenet-B"
KLING_MAX_DUR = 10  # Kling maximum clip duration; split only if narration exceeds this


def split_scenes(
    script: list[dict],
    workspace: Path,
    video_style: str,
    sop_title: str,
    duration: int,
    equipment_type: str = "",
    domain: str = "industrial",
) -> SceneManifest:
    """Synthesize TTS per scene, split >10s scenes, write manifest.json.

    `domain` controls the character prefix used in image_prompt
    (industrial / lab / medical / chemical / construction / general).
    """
    audio_dir = workspace / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    tts_provider: str | None = None
    tts_voice: str | None = None
    scenes: list[Scene] = []

    for raw in script:
        scene_id = raw.get("scene_id") or f"S{len(scenes)+1:02d}"
        narration = raw.get("narration_ko") or ""
        # Determine duration:
        # - If narration is non-empty: synthesize TTS, derive duration from audio.
        # - If narration is empty: use the script's duration_sec field (set by ScenarioAgent),
        #   skip TTS, and emit a silent placeholder wav for downstream stages.
        if narration:
            provider = tts_provider or DEFAULT_PROVIDER
            voice = tts_voice or DEFAULT_VOICE
            audio_path = audio_dir / f"{scene_id}.wav"
            _, dur_sec = synthesize(
                text=narration,
                provider=provider,
                voice=voice,
                output_path=audio_path,
            )
            if tts_provider is None:
                tts_provider = provider
                tts_voice = voice
            duration_sec = math.ceil(dur_sec)
        else:
            duration_sec = int(raw.get("duration_sec") or 5)
            duration_sec = max(1, min(KLING_MAX_DUR, duration_sec))
            audio_path = audio_dir / f"{scene_id}.wav"
            _write_silent_wav(audio_path, duration_sec)
            console.print(
                f"[dim]{scene_id}: silent placeholder ({duration_sec}s, no narration)[/dim]"
            )

        if duration_sec <= KLING_MAX_DUR:
            scenes.append(_make_scene(raw, scene_id, duration_sec, equipment_type, domain))
        else:
            offset = 0
            suffix_idx = 0
            while offset < duration_sec:
                chunk_dur = min(KLING_MAX_DUR, duration_sec - offset)
                suffix = chr(ord('a') + suffix_idx)
                sub_id = f"{scene_id}{suffix}"
                sub_audio = audio_dir / f"{sub_id}.wav"
                is_last = (offset + chunk_dur >= duration_sec)
                _split_audio_file(
                    audio_path, sub_audio,
                    start=offset,
                    length=None if is_last else chunk_dur,
                )
                scenes.append(_make_scene(raw, sub_id, chunk_dur, equipment_type, domain))
                offset += chunk_dur
                suffix_idx += 1

    manifest = SceneManifest(
        sop_title=sop_title,
        total_duration_sec=sum(s.duration_sec for s in scenes),
        video_style=video_style,
        tts_provider=tts_provider,
        tts_voice=tts_voice,
        scenes=scenes,
    )

    (workspace / "manifest.json").write_text(
        manifest.model_dump_json(indent=2), encoding="utf-8"
    )
    return manifest


def _make_scene(raw: dict, scene_id: str, duration_sec: int, equipment_type: str, domain: str = "industrial") -> Scene:
    bgm = raw.get("bgm_keywords") or []
    if not isinstance(bgm, list):
        bgm = []
    return Scene(
        scene_id=scene_id,
        act=raw["act"],
        duration_sec=duration_sec,
        status=SceneStatus.audio_ready,
        narration_ko=raw.get("narration_ko") or "",
        image_prompt=build_image_prompt(raw["image_prompt"], equipment=equipment_type, domain=domain),
        motion_prompt=raw["motion_prompt"],
        camera=raw["camera"],
        mood=raw["mood"],
        on_screen_text=raw.get("on_screen_text"),
        bgm_keywords=[str(k) for k in bgm],
    )


def _split_audio_file(
    source: Path, dest: Path, start: int, length: int | None
) -> None:
    cmd = ["ffmpeg", "-y", "-i", str(source), "-ss", str(start)]
    if length is not None:
        cmd += ["-t", str(length)]
    cmd += ["-acodec", "copy", str(dest)]
    subprocess.run(cmd, check=True, capture_output=True)


def _write_silent_wav(out_path: Path, duration_sec: int) -> None:
    """Create a silent stereo wav of given duration. Used when no narration is set."""
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"anullsrc=channel_layout=mono:sample_rate=44100",
        "-t", str(duration_sec),
        "-acodec", "pcm_s16le",
        str(out_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
