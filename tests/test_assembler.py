from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest
from pipeline.assembler import assemble, AssemblyError
from models.scene_manifest import Scene, SceneManifest, SceneStatus


def _make_ready_manifest(workspace: Path) -> SceneManifest:
    (workspace / "clips").mkdir(parents=True)
    (workspace / "audio").mkdir(parents=True)
    (workspace / "clips" / "S01.mp4").write_bytes(b"\x00" * 100)
    (workspace / "audio" / "S01.mp3").write_bytes(b"\x00" * 100)

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
    fake_output.write_bytes(b"\x00" * 10)

    with patch("pipeline.assembler.subprocess.run") as mock_run, \
         patch("pipeline.assembler._audio_duration", return_value=7.5), \
         patch("pipeline.assembler._final_output_path", return_value=fake_output):
        mock_run.return_value = MagicMock(returncode=0)
        result = assemble(manifest=manifest, workspace=workspace, output_dir=output_dir)

    assert result == fake_output
    assert mock_run.call_count >= 2


def test_assemble_raises_when_clip_missing(tmp_path):
    workspace = tmp_path / "ws"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    manifest = _make_ready_manifest(workspace)
    (workspace / "clips" / "S01.mp4").unlink()

    with pytest.raises(AssemblyError, match="missing clip"):
        assemble(manifest=manifest, workspace=workspace, output_dir=output_dir)


def test_assemble_skips_skipped_scenes(tmp_path):
    workspace = tmp_path / "ws"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    manifest = _make_ready_manifest(workspace)
    manifest.scenes[0].status = SceneStatus.skipped

    with patch("pipeline.assembler.subprocess.run") as mock_run:
        with pytest.raises(AssemblyError, match="No assemblable scenes"):
            assemble(manifest=manifest, workspace=workspace, output_dir=output_dir)
