from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest
from pipeline.tts import synthesize, TtsError


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
