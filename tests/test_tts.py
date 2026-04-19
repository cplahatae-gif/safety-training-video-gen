import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from pipeline.tts import synthesize, TtsError, _audio_duration


def test_synthesize_google_writes_mp3_and_returns_duration(tmp_path):
    fake_audio = b"ID3" + b"\x00" * 200

    with patch("pipeline.tts.texttospeech.TextToSpeechClient") as mock_cls, \
         patch("pipeline.tts._audio_duration", return_value=5.4):
        mock_client = MagicMock()
        mock_client.synthesize_speech.return_value = MagicMock(audio_content=fake_audio)
        mock_cls.return_value = mock_client

        output_path = tmp_path / "S01.mp3"
        audio_bytes, duration = synthesize(
            text="아웃리거를 완전히 전개하세요.",
            provider="google",
            voice="ko-KR-Wavenet-B",
            output_path=output_path,
        )

    assert output_path.exists()
    assert output_path.read_bytes() == fake_audio
    assert audio_bytes == fake_audio
    assert duration == pytest.approx(5.4)


def test_synthesize_raises_on_unknown_provider(tmp_path):
    with pytest.raises(TtsError, match="Unknown provider"):
        synthesize(
            text="x",
            provider="bogus",
            voice="v",
            output_path=tmp_path / "x.mp3",
        )


def test_audio_duration_wraps_ffprobe_missing(tmp_path):
    fake = tmp_path / "a.mp3"
    fake.write_bytes(b"x")
    with patch("pipeline.tts.subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(TtsError, match="ffprobe not found"):
            _audio_duration(fake)


def test_audio_duration_wraps_ffprobe_failure(tmp_path):
    fake = tmp_path / "a.mp3"
    fake.write_bytes(b"x")
    err = subprocess.CalledProcessError(1, "ffprobe", stderr="Invalid data found")
    with patch("pipeline.tts.subprocess.run", side_effect=err):
        with pytest.raises(TtsError, match="ffprobe failed"):
            _audio_duration(fake)


def test_synthesize_raises_on_empty_audio(tmp_path):
    with patch("pipeline.tts.texttospeech.TextToSpeechClient") as mock_cls:
        mock_client = MagicMock()
        mock_client.synthesize_speech.return_value = MagicMock(audio_content=b"")
        mock_cls.return_value = mock_client

        with pytest.raises(TtsError, match="empty audio"):
            synthesize(
                text="테스트",
                provider="google",
                voice="ko-KR-Wavenet-B",
                output_path=tmp_path / "S01.mp3",
            )
