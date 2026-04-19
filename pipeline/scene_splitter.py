from __future__ import annotations
import json
import math
import subprocess
from pathlib import Path

from models.scene_manifest import Scene, SceneManifest, SceneStatus
from pipeline.tts import synthesize
from prompts.scene_prompt import build_image_prompt

DEFAULT_PROVIDER = "google"
DEFAULT_VOICE = "ko-KR-Wavenet-B"


def split_scenes(
    script: list[dict],
    workspace: Path,
    video_style: str,
    sop_title: str,
    duration: int,
) -> SceneManifest:
    """Synthesize TTS per scene, split >8s scenes, write manifest.json."""
    audio_dir = workspace / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)

    tts_provider: str | None = None
    tts_voice: str | None = None
    scenes: list[Scene] = []

    for raw in script:
        scene_id = raw["scene_id"]
        narration = raw["narration_ko"]
        provider = tts_provider or DEFAULT_PROVIDER
        voice = tts_voice or DEFAULT_VOICE

        audio_path = audio_dir / f"{scene_id}.mp3"
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

        if duration_sec <= 8:
            scenes.append(_make_scene(raw, scene_id, duration_sec))
        else:
            offset = 0
            suffix_idx = 0
            while offset < duration_sec:
                chunk_dur = min(8, duration_sec - offset)
                suffix = chr(ord('a') + suffix_idx)
                sub_id = f"{scene_id}{suffix}"
                sub_audio = audio_dir / f"{sub_id}.mp3"
                is_last = (offset + chunk_dur >= duration_sec)
                _split_audio_file(
                    audio_path, sub_audio,
                    start=offset,
                    length=None if is_last else chunk_dur,
                )
                scenes.append(_make_scene(raw, sub_id, chunk_dur))
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


def _make_scene(raw: dict, scene_id: str, duration_sec: int) -> Scene:
    return Scene(
        scene_id=scene_id,
        act=raw["act"],
        duration_sec=duration_sec,
        status=SceneStatus.audio_ready,
        narration_ko=raw["narration_ko"],
        image_prompt=build_image_prompt(raw["image_prompt"]),
        motion_prompt=raw["motion_prompt"],
        camera=raw["camera"],
        mood=raw["mood"],
        on_screen_text=raw.get("on_screen_text"),
    )


def _split_audio_file(
    source: Path, dest: Path, start: int, length: int | None
) -> None:
    cmd = ["ffmpeg", "-y", "-i", str(source), "-ss", str(start)]
    if length is not None:
        cmd += ["-t", str(length)]
    cmd += ["-acodec", "copy", str(dest)]
    subprocess.run(cmd, check=True, capture_output=True)
