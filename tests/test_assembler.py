from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest
from pipeline.assembler import assemble, AssemblyError, _generate_outro_clip
from models.scene_manifest import Scene, SceneManifest, SceneStatus


def _make_ready_manifest(workspace: Path) -> SceneManifest:
    (workspace / "clips").mkdir(parents=True)
    (workspace / "audio").mkdir(parents=True)
    (workspace / "clips" / "S01.mp4").write_bytes(b"\x00" * 100)
    (workspace / "audio" / "S01.wav").write_bytes(b"\x00" * 100)

    return SceneManifest(
        sop_title="테스트 SOP", total_duration_sec=8,
        video_style="hybrid", tts_provider="google", tts_voice="ko-KR-Wavenet-B",
        scenes=[
            Scene(
                scene_id="S01", act="hook", duration_sec=8,
                status=SceneStatus.clip_ready,
                narration_ko="나레이션", image_prompt="prompt",
                motion_prompt="pan", camera="wide", mood="tense",
            )
        ],
    )


def test_assemble_calls_ffmpeg_and_returns_output_path(tmp_path):
    workspace = tmp_path / "ws"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    manifest = _make_ready_manifest(workspace)

    fake_output = output_dir / "result.mp4"

    def _fake_ffmpeg(cmd, **kwargs):
        # Create whatever output file ffmpeg would have produced
        for i, arg in enumerate(cmd):
            if arg not in ("-y", "-i", "-f", "-safe", "-c", "-vf", "-r", "-t",
                           "-c:v", "-preset", "-c:a", "-b:a", "-ar", "-ac",
                           "ffmpeg", "concat", "0", "copy", "libx264", "fast",
                           "aac", "192k", "44100", "2", "24", "null"):
                path = Path(arg)
                if path.suffix == ".mp4" and not path.exists():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"\x00" * 100)
        return MagicMock(returncode=0)

    with patch("pipeline.assembler.subprocess.run", side_effect=_fake_ffmpeg), \
         patch("pipeline.assembler._audio_duration", return_value=7.5), \
         patch("pipeline.assembler._final_output_path", return_value=fake_output):
        result = assemble(manifest=manifest, workspace=workspace, output_dir=output_dir)

    assert result == fake_output
    assert result.exists()


def test_assemble_raises_when_clip_missing(tmp_path):
    workspace = tmp_path / "ws"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    manifest = _make_ready_manifest(workspace)
    (workspace / "clips" / "S01.mp4").unlink()

    with pytest.raises(AssemblyError, match="missing clip"):
        assemble(manifest=manifest, workspace=workspace, output_dir=output_dir)


def test_outro_skipped_when_no_narration(tmp_path):
    import config as _cfg
    with patch.object(_cfg, "OUTRO_NARRATION", ""):
        result = _generate_outro_clip(tmp_path)
    assert result is None


def test_outro_skips_tts_on_synthesize_failure(tmp_path):
    import config as _cfg
    with patch.object(_cfg, "OUTRO_NARRATION", "마무리 멘트"), \
         patch.object(_cfg, "OUTRO_IMAGE", ""), \
         patch("pipeline.assembler.synthesize", side_effect=RuntimeError("TTS failed")):
        result = _generate_outro_clip(tmp_path)
    assert result is None
    assert not (tmp_path / "_outro.wav").exists()


def test_outro_uses_lavfi_when_no_image(tmp_path):
    import config as _cfg
    fake_wav = tmp_path / "_outro.wav"
    fake_wav.write_bytes(b"\x00" * 2000)

    def _fake_ffmpeg(cmd, **kwargs):
        out = Path(cmd[-1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"\x00" * 100)
        return MagicMock(returncode=0)

    with patch.object(_cfg, "OUTRO_NARRATION", "마무리 멘트"), \
         patch.object(_cfg, "OUTRO_IMAGE", ""), \
         patch("pipeline.assembler._audio_duration", return_value=5.0), \
         patch("pipeline.assembler.subprocess.run", side_effect=_fake_ffmpeg):
        result = _generate_outro_clip(tmp_path)

    assert result is not None
    assert result.name == "_outro.mp4"


def test_assemble_appends_outro_to_concat(tmp_path):
    workspace = tmp_path / "ws"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    manifest = _make_ready_manifest(workspace)

    fake_output = output_dir / "result.mp4"
    fake_outro = tmp_path / "ws" / "tmp" / "_outro.mp4"

    def _fake_ffmpeg(cmd, **kwargs):
        for arg in cmd:
            path = Path(arg)
            if path.suffix == ".mp4" and not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"\x00" * 100)
        return MagicMock(returncode=0)

    with patch("pipeline.assembler.subprocess.run", side_effect=_fake_ffmpeg), \
         patch("pipeline.assembler._audio_duration", return_value=7.5), \
         patch("pipeline.assembler._final_output_path", return_value=fake_output), \
         patch("pipeline.assembler._generate_outro_clip", return_value=fake_outro) as mock_outro:
        fake_outro.parent.mkdir(parents=True, exist_ok=True)
        fake_outro.write_bytes(b"\x00" * 100)
        result = assemble(manifest=manifest, workspace=workspace, output_dir=output_dir)

    mock_outro.assert_called_once()
    concat_list = workspace / "tmp" / "concat.txt"
    assert concat_list.exists()
    content = concat_list.read_text(encoding="utf-8")
    assert "_outro.mp4" in content


def test_assemble_skips_skipped_scenes(tmp_path):
    workspace = tmp_path / "ws"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    manifest = _make_ready_manifest(workspace)
    manifest.scenes[0].status = SceneStatus.skipped

    with patch("pipeline.assembler.subprocess.run") as mock_run:
        with pytest.raises(AssemblyError, match="No assemblable scenes"):
            assemble(manifest=manifest, workspace=workspace, output_dir=output_dir)
