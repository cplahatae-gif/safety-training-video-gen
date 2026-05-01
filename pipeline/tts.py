from __future__ import annotations
import subprocess
from pathlib import Path

from google.cloud import texttospeech


class TtsError(Exception):
    pass


def synthesize(
    text: str,
    provider: str,
    voice: str,
    output_path: Path,
) -> tuple[bytes, float]:
    """Synthesize text to speech, write to output_path, return (audio_bytes, duration_sec)."""
    if provider == "google":
        audio_bytes = _google_tts(text, voice)
    elif provider == "elevenlabs":
        audio_bytes = _elevenlabs_tts(text, voice)
    else:
        raise TtsError(f"Unknown provider: {provider}")

    if not audio_bytes:
        raise TtsError("empty audio returned from TTS provider")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio_bytes)

    duration = _audio_duration(output_path)
    return audio_bytes, duration


def _google_tts(text: str, voice: str) -> bytes:
    import config as _cfg
    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice_params = texttospeech.VoiceSelectionParams(
        language_code="ko-KR",
        name=voice,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.LINEAR16,
        sample_rate_hertz=_cfg.TTS_SAMPLE_RATE,
    )
    response = client.synthesize_speech(
        input=synthesis_input,
        voice=voice_params,
        audio_config=audio_config,
    )
    return response.audio_content


def _elevenlabs_tts(text: str, voice_id: str) -> bytes:
    import os
    import httpx

    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    if not api_key:
        raise TtsError("ELEVENLABS_API_KEY not set")
    try:
        response = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json={"text": text, "model_id": "eleven_multilingual_v2"},
            timeout=30,
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        raise TtsError(f"ElevenLabs returned {e.response.status_code}: {e.response.text[:200]}") from e
    except httpx.RequestError as e:
        raise TtsError(f"ElevenLabs network error: {e}") from e
    return response.content


def _audio_duration(audio_path: Path) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as e:
        raise TtsError("ffprobe not found on PATH — install ffmpeg (winget install ffmpeg)") from e
    except subprocess.CalledProcessError as e:
        raise TtsError(f"ffprobe failed on {audio_path}: {e.stderr.strip()}") from e
    return float(result.stdout.strip())
