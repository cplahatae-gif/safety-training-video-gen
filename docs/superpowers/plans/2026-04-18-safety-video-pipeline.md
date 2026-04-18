# Safety Training Video Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a 7-stage CLI pipeline that converts SOP DOCX/PDF files into finished 1080p MP4 safety training videos, with per-scene TTS narration, FLUX keyframes, and Kling motion clips.

**Architecture:** Each stage is an independent Python module in `pipeline/`. Stages communicate via `workspace/<run_id>/` directory (manifest.json as shared state, images/, clips/, audio/ for artifacts). `manifest.json` carries a `status` field per scene so partial reruns and partial failures are handled gracefully. TTS is synthesized in Stage 3; Stage 6 fills gaps for any scenes missing audio (e.g., sub-scene splits or partial re-runs).

**Tech Stack:** Python 3.12, uv, google-generativeai>=0.8.0, fal-client, google-cloud-texttospeech, python-docx, pdfplumber, pydantic>=2.0, python-ffmpeg, python-dotenv, rich, pytest

---

## File Map

| File | Purpose |
|------|---------|
| `pyproject.toml` | uv project config + dependencies |
| `config.py` | Loads `.env`, exposes typed constants |
| `.env.example` | Template for required env vars |
| `main.py` | CLI entrypoint (argparse) |
| `models/__init__.py` | Package init |
| `models/scene_manifest.py` | Pydantic: `SceneManifest`, `Scene`, `SceneStatus`, `SopJson` |
| `prompts/script_prompt.py` | Gemini system + user prompt templates for script generation |
| `prompts/scene_prompt.py` | Character prefix + image/motion prompt builder |
| `pipeline/__init__.py` | Package init |
| `pipeline/tts.py` | `synthesize(text, provider, voice, output_path) -> (bytes, float)` |
| `pipeline/sop_parser.py` | `parse_sop(path) -> dict` — DOCX/PDF → SOP JSON |
| `pipeline/script_gen.py` | `generate_script(sop, duration) -> list[dict]` — Gemini → scenes |
| `pipeline/scene_splitter.py` | `split_scenes(script, workspace, run_id) -> SceneManifest` — TTS + manifest |
| `pipeline/image_gen.py` | `generate_images(manifest, workspace) -> SceneManifest` — FLUX |
| `pipeline/video_gen.py` | `generate_videos(manifest, workspace) -> SceneManifest` — Kling |
| `pipeline/assembler.py` | `assemble(manifest, workspace, output_dir) -> Path` — FFmpeg |
| `tests/conftest.py` | Shared fixtures |
| `tests/test_models.py` | Pydantic model validation |
| `tests/test_tts.py` | TTS synthesize + file write |
| `tests/test_sop_parser.py` | DOCX/PDF parse + Gemini structuring |
| `tests/test_script_gen.py` | Script generation via Gemini |
| `tests/test_scene_splitter.py` | Scene splitting, TTS call, sub-scene logic |
| `tests/test_image_gen.py` | Image generation with fal mocking |
| `tests/test_video_gen.py` | Video generation with fal mocking |
| `tests/test_assembler.py` | FFmpeg assembly with subprocess mocking |
| `tests/test_cli.py` | CLI argument parsing |
| `tests/fixtures/sample_sop.json` | Fixture SOP JSON |

---

## Task 1: Project Setup

**Files:**
- Create: `pyproject.toml`
- Create: `config.py`
- Create: `.env.example`
- Create: `pipeline/__init__.py`
- Create: `models/__init__.py`
- Create: `prompts/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/fixtures/sample_sop.json`

- [ ] **Step 1: Initialize uv project**

```bash
cd "E:/.shortcut-targets-by-id/1A0SIVshe4TvCKXlR-jr-FdeHp3oYIIPJ/구글 동기화/claude/safety-training-video-gen"
uv init --python 3.12
```

Expected: `pyproject.toml` and `.python-version` created.

- [ ] **Step 2: Add all dependencies**

```bash
uv add google-generativeai pydantic python-dotenv rich
uv add python-docx pdfplumber
uv add fal-client
uv add google-cloud-texttospeech
uv add python-ffmpeg
uv add httpx
uv add --dev pytest pytest-mock
```

Expected: `uv.lock` updated, all packages installed.

- [ ] **Step 3: Write `config.py`**

```python
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
FAL_KEY: str = os.getenv("FAL_KEY", "")
GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")

DEFAULT_IMAGE_MODEL: str = os.getenv("DEFAULT_IMAGE_MODEL", "fal-ai/flux/schnell")
DEFAULT_VIDEO_MODEL: str = os.getenv("DEFAULT_VIDEO_MODEL", "fal-ai/kling-video/v3/pro/image-to-video")
USE_FLUX_DEV: bool = os.getenv("USE_FLUX_DEV", "false").lower() == "true"
DEFAULT_DURATION: int = int(os.getenv("DEFAULT_DURATION", "180"))
MAX_RETRY: int = int(os.getenv("MAX_RETRY", "1"))
WORKSPACE_DIR: Path = Path(os.getenv("WORKSPACE_DIR", "./workspace"))
OUTPUT_DIR: Path = Path(os.getenv("OUTPUT_DIR", "./output"))
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
```

- [ ] **Step 4: Write `.env.example`**

```
GEMINI_API_KEY=
FAL_KEY=
GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json
ELEVENLABS_API_KEY=

DEFAULT_IMAGE_MODEL=fal-ai/flux/schnell
DEFAULT_VIDEO_MODEL=fal-ai/kling-video/v3/pro/image-to-video
USE_FLUX_DEV=false
DEFAULT_DURATION=180
MAX_RETRY=1
WORKSPACE_DIR=./workspace
OUTPUT_DIR=./output
```

- [ ] **Step 5: Create package `__init__.py` files and fixture**

Create empty `pipeline/__init__.py`, `models/__init__.py`, `prompts/__init__.py`, `tests/__init__.py`.

Create `tests/fixtures/sample_sop.json`:
```json
{
  "sop_title": "고소작업차 운용 표준 안전작업지침",
  "legal_basis": ["산업안전보건기준에 관한 규칙 제186조"],
  "hazards": [{"id": "H1", "name": "추락", "severity": "사망"}],
  "procedure_steps": [
    {"step": 1, "action": "작업 전 점검", "key_rules": ["아웃리거 완전 전개"]}
  ],
  "target_audience": "중장비 운전자",
  "common_violations": ["안전대 미착용"]
}
```

Create `tests/conftest.py`:
```python
import json
from pathlib import Path
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

@pytest.fixture
def sample_sop() -> dict:
    return json.loads((FIXTURES_DIR / "sample_sop.json").read_text(encoding="utf-8"))
```

- [ ] **Step 6: Verify import works**

```bash
uv run python -c "import config; print('config OK')"
```

Expected: `config OK`

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock config.py .env.example pipeline/ models/ prompts/ tests/
git commit -m "feat: project setup — pyproject.toml, config, fixtures"
```

---

## Task 2: Data Models

**Files:**
- Create: `models/scene_manifest.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_models.py
import pytest
from models.scene_manifest import Scene, SceneManifest, SceneStatus, SopJson

def test_scene_status_lifecycle():
    scene = Scene(
        scene_id="S01", act="hook", duration_sec=8,
        narration_ko="테스트입니다.",
        image_prompt="Korean construction site",
        motion_prompt="slow pan left",
        camera="wide shot", mood="tense"
    )
    assert scene.status == SceneStatus.pending
    assert scene.on_screen_text is None

def test_scene_manifest_round_trip():
    manifest = SceneManifest(
        sop_title="테스트 SOP", total_duration_sec=8,
        video_style="hybrid", tts_provider="google",
        tts_voice="ko-KR-Wavenet-B",
        scenes=[
            Scene(
                scene_id="S01", act="hook", duration_sec=8,
                narration_ko="나레이션", image_prompt="prompt",
                motion_prompt="motion", camera="wide", mood="tense"
            )
        ]
    )
    data = manifest.model_dump()
    restored = SceneManifest.model_validate(data)
    assert restored.sop_title == "테스트 SOP"
    assert restored.scenes[0].status == SceneStatus.pending

def test_sop_json_validates():
    sop = SopJson(
        sop_title="테스트", legal_basis=[], hazards=[],
        procedure_steps=[{"step": 1, "action": "점검", "key_rules": []}],
        target_audience="작업자", common_violations=[]
    )
    assert sop.sop_title == "테스트"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_models.py -v
```

Expected: `ImportError: No module named 'models.scene_manifest'`

- [ ] **Step 3: Write `models/scene_manifest.py`**

```python
from __future__ import annotations
from enum import Enum
from typing import Optional, Literal
from pydantic import BaseModel


class SceneStatus(str, Enum):
    pending = "pending"
    audio_ready = "audio_ready"
    image_ready = "image_ready"
    clip_ready = "clip_ready"
    merged_ready = "merged_ready"   # per-scene merge done; final concat pending
    assembled = "assembled"
    skipped = "skipped"


class Scene(BaseModel):
    scene_id: str
    act: str
    duration_sec: int
    status: SceneStatus = SceneStatus.pending
    narration_ko: str
    image_prompt: str
    motion_prompt: str
    camera: str
    mood: str
    on_screen_text: Optional[str] = None


class SceneManifest(BaseModel):
    sop_title: str
    total_duration_sec: int
    video_style: Literal["hybrid", "shortform"]
    tts_provider: Optional[str] = None
    tts_voice: Optional[str] = None
    scenes: list[Scene]

    def save(self, workspace: Path) -> None:
        """Persist manifest.json to workspace directory."""
        (workspace / "manifest.json").write_text(
            self.model_dump_json(indent=2), encoding="utf-8"
        )


class Hazard(BaseModel):
    id: str
    name: str
    severity: str


class ProcedureStep(BaseModel):
    step: int
    action: str
    key_rules: list[str]


class SopJson(BaseModel):
    sop_title: str
    legal_basis: list[str]
    hazards: list[Hazard]
    procedure_steps: list[ProcedureStep]
    target_audience: str
    common_violations: list[str]
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_models.py -v
```

Expected: 3 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add models/scene_manifest.py tests/test_models.py
git commit -m "feat: Pydantic data models — SceneManifest, SopJson, SceneStatus"
```

---

## Task 3: Prompts

**Files:**
- Create: `prompts/script_prompt.py`
- Create: `prompts/scene_prompt.py`

- [ ] **Step 1: Write `prompts/script_prompt.py`**

```python
SYSTEM_PROMPT = """당신은 산업 안전교육 영상 대본 전문가입니다.
SOP 문서를 분석하여 현장 근로자를 위한 안전교육 영상 대본을 작성합니다.
- 나레이션: 한국어로 작성, 짧고 명확하게 (씬당 1~3문장)
- 이미지 프롬프트: 영어로 작성, Stable Diffusion 스타일
- 3막 구조 준수: hook → conflict/consequence → resolution/rules
"""

THREE_MIN_TEMPLATE = """다음 SOP를 분석하여 3분 안전교육 영상 대본을 JSON으로 작성하세요.

SOP 내용:
{sop_json}

요구사항:
- 총 {scene_count}개 씬 (각 8초 이하)
- 3막 구조: hook 1개, conflict+consequence 여러 개, resolution+rules로 마무리
- 각 씬: scene_id, act, narration_ko, image_prompt, motion_prompt, camera, mood, on_screen_text

JSON 형식으로만 응답하세요 (배열):
[{{"scene_id": "S01", "act": "hook", "narration_ko": "...", "image_prompt": "...", "motion_prompt": "...", "camera": "...", "mood": "...", "on_screen_text": null}}]
"""

SHORTFORM_TEMPLATE = """다음 SOP를 분석하여 30초 안전교육 영상 대본을 JSON으로 작성하세요.

SOP 내용:
{sop_json}

요구사항:
- 총 4개 씬 (각 7~8초)
- 핵심 위험 1가지에 집중
- JSON 형식으로만 응답하세요 (배열)
"""
```

- [ ] **Step 2: Write `prompts/scene_prompt.py`**

```python
CHARACTER_PREFIX = (
    "Korean male worker, Sampyo navy blue uniform with company logo, "
    "reflective yellow stripes, white hard hat with Sampyo logo, "
    "safety gloves, steel-toe boots, "
)

def build_image_prompt(scene_image_prompt: str) -> str:
    """Prepend character consistency prefix to every image prompt."""
    return f"{CHARACTER_PREFIX}{scene_image_prompt}"
```

- [ ] **Step 3: Verify import**

```bash
uv run python -c "from prompts.script_prompt import SYSTEM_PROMPT; from prompts.scene_prompt import build_image_prompt; print(build_image_prompt('construction site')[:60])"
```

Expected: First 60 chars of the prefixed prompt.

- [ ] **Step 4: Commit**

```bash
git add prompts/script_prompt.py prompts/scene_prompt.py
git commit -m "feat: prompt templates for script generation and image prompts"
```

---

## Task 4: TTS Module

**Files:**
- Create: `pipeline/tts.py`
- Create: `tests/test_tts.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_tts.py
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_tts.py -v
```

Expected: `ImportError: No module named 'pipeline.tts'`

- [ ] **Step 3: Write `pipeline/tts.py`**

```python
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
    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice_params = texttospeech.VoiceSelectionParams(
        language_code="ko-KR",
        name=voice,
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
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
    response = httpx.post(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
        headers={"xi-api-key": api_key, "Content-Type": "application/json"},
        json={"text": text, "model_id": "eleven_multilingual_v2"},
        timeout=30,
    )
    response.raise_for_status()
    return response.content


def _audio_duration(audio_path: Path) -> float:
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
    return float(result.stdout.strip())
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_tts.py -v
```

Expected: 2 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add pipeline/tts.py tests/test_tts.py
git commit -m "feat: TTS module — Google WaveNet + ElevenLabs fallback, audio duration via ffprobe"
```

---

## Task 5: SOP Parser

**Files:**
- Create: `pipeline/sop_parser.py`
- Create: `tests/test_sop_parser.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_sop_parser.py
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from pipeline.sop_parser import parse_sop, ParseError

EXPECTED_SOP = {
    "sop_title": "테스트 SOP",
    "legal_basis": [],
    "hazards": [],
    "procedure_steps": [{"step": 1, "action": "점검", "key_rules": []}],
    "target_audience": "작업자",
    "common_violations": [],
}


def test_parse_docx_returns_sop_json(tmp_path, sample_sop):
    fake_docx = tmp_path / "test.docx"
    fake_docx.write_bytes(b"PK\x03\x04")  # minimal zip magic bytes

    with patch("pipeline.sop_parser._extract_text_docx", return_value="SOP 원문 텍스트"), \
         patch("pipeline.sop_parser._gemini_structure", return_value=EXPECTED_SOP):
        result = parse_sop(fake_docx, run_workspace=tmp_path)

    assert result["sop_title"] == "테스트 SOP"
    assert (tmp_path / "sop.json").exists()


def test_parse_pdf_returns_sop_json(tmp_path):
    fake_pdf = tmp_path / "test.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4")

    with patch("pipeline.sop_parser._extract_text_pdf", return_value="SOP 원문 텍스트"), \
         patch("pipeline.sop_parser._gemini_structure", return_value=EXPECTED_SOP):
        result = parse_sop(fake_pdf, run_workspace=tmp_path)

    assert result["sop_title"] == "테스트 SOP"


def test_parse_unknown_extension_raises(tmp_path):
    bad_file = tmp_path / "test.hwp"
    bad_file.write_bytes(b"dummy")

    with pytest.raises(ParseError, match="Unsupported file type"):
        parse_sop(bad_file, run_workspace=tmp_path)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_sop_parser.py -v
```

Expected: `ImportError: No module named 'pipeline.sop_parser'`

- [ ] **Step 3: Write `pipeline/sop_parser.py`**

```python
from __future__ import annotations
import json
from pathlib import Path

import pdfplumber
from docx import Document

import config
from models.scene_manifest import SopJson
from prompts.script_prompt import SYSTEM_PROMPT


class ParseError(Exception):
    pass


def parse_sop(sop_path: Path, run_workspace: Path) -> dict:
    """Parse SOP DOCX/PDF → structured JSON. Writes sop.json to run_workspace."""
    suffix = sop_path.suffix.lower()
    if suffix == ".docx":
        text = _extract_text_docx(sop_path)
    elif suffix == ".pdf":
        text = _extract_text_pdf(sop_path)
    else:
        raise ParseError(f"Unsupported file type: {suffix}. Supported: .docx, .pdf")

    if not text.strip():
        raise ParseError(f"Could not extract text from {sop_path.name}")

    sop_data = _gemini_structure(text)

    try:
        SopJson.model_validate(sop_data)
    except Exception as exc:
        raise ParseError(f"SOP schema validation failed: {exc}") from exc

    run_workspace.mkdir(parents=True, exist_ok=True)
    (run_workspace / "sop.json").write_text(
        json.dumps(sop_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return sop_data


def _extract_text_docx(path: Path) -> str:
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_text_pdf(path: Path) -> str:
    lines: list[str] = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                lines.append(text)
    return "\n".join(lines)


def _gemini_structure(raw_text: str) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=config.GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name=config.GEMINI_MODEL,
        system_instruction=SYSTEM_PROMPT,
    )
    prompt = f"""다음 SOP 원문을 분석하여 JSON으로 구조화하세요.

원문:
{raw_text}

다음 JSON 스키마로 응답하세요 (JSON만, 다른 텍스트 없이):
{{
  "sop_title": "string",
  "legal_basis": ["string"],
  "hazards": [{{"id": "H1", "name": "string", "severity": "string"}}],
  "procedure_steps": [{{"step": 1, "action": "string", "key_rules": ["string"]}}],
  "target_audience": "string",
  "common_violations": ["string"]
}}"""

    for attempt in range(config.MAX_RETRY + 1):
        try:
            response = model.generate_content(prompt)
            # Guard: safety block or empty response raises before parsing
            if not response.candidates or not response.candidates[0].content.parts:
                finish = getattr(response.candidates[0], "finish_reason", "unknown") if response.candidates else "no_candidates"
                raise ParseError(f"Gemini returned no content (finish_reason={finish})")
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as exc:
            if attempt == config.MAX_RETRY:
                raise ParseError(f"Gemini API failed after {config.MAX_RETRY + 1} attempts: {exc}") from exc
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_sop_parser.py -v
```

Expected: 3 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add pipeline/sop_parser.py tests/test_sop_parser.py
git commit -m "feat: SOP parser — DOCX/PDF text extraction + Claude structuring"
```

---

## Task 6: Script Generator

**Files:**
- Create: `pipeline/script_gen.py`
- Create: `tests/test_script_gen.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_script_gen.py
import json
from unittest.mock import MagicMock, patch
import pytest
import google.generativeai as genai
from pipeline.script_gen import generate_script

FAKE_SCENES = [
    {
        "scene_id": "S01", "act": "hook",
        "narration_ko": "아웃리거를 전개하지 않으면 이런 일이 생깁니다.",
        "image_prompt": "aerial work platform truck tilting",
        "motion_prompt": "truck tilts slowly",
        "camera": "low angle", "mood": "tense", "on_screen_text": None
    }
]


def test_generate_script_3min_returns_scene_list(sample_sop):
    mock_response = MagicMock()
    mock_response.text = json.dumps(FAKE_SCENES)
    with patch("pipeline.script_gen.genai.GenerativeModel") as mock_model_cls:
        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_response
        mock_model_cls.return_value = mock_model

        scenes = generate_script(sop=sample_sop, duration=180)

    assert isinstance(scenes, list)
    assert len(scenes) == 1
    assert scenes[0]["scene_id"] == "S01"
    assert "narration_ko" in scenes[0]
    assert "image_prompt" in scenes[0]


def test_generate_script_30sec_uses_shortform_template(sample_sop):
    mock_response = MagicMock()
    mock_response.text = json.dumps(FAKE_SCENES)
    with patch("pipeline.script_gen.genai.GenerativeModel") as mock_model_cls:
        mock_model = MagicMock()
        mock_model.generate_content.return_value = mock_response
        mock_model_cls.return_value = mock_model

        scenes = generate_script(sop=sample_sop, duration=30)
        call_args = mock_model.generate_content.call_args

    user_content = call_args[0][0]
    assert "30초" in user_content or "shortform" in user_content.lower()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_script_gen.py -v
```

Expected: `ImportError: No module named 'pipeline.script_gen'`

- [ ] **Step 3: Write `pipeline/script_gen.py`**

```python
from __future__ import annotations
import json

import google.generativeai as genai

import config
from prompts.script_prompt import SYSTEM_PROMPT, THREE_MIN_TEMPLATE, SHORTFORM_TEMPLATE


def generate_script(sop: dict, duration: int) -> list[dict]:
    """Call Gemini to generate a list of scene dicts from SOP JSON."""
    genai.configure(api_key=config.GEMINI_API_KEY)
    model = genai.GenerativeModel(
        model_name=config.GEMINI_MODEL,
        system_instruction=SYSTEM_PROMPT,
    )

    if duration <= 30:
        user_prompt = SHORTFORM_TEMPLATE.format(sop_json=json.dumps(sop, ensure_ascii=False))
    else:
        scene_count = duration // 8
        user_prompt = THREE_MIN_TEMPLATE.format(
            sop_json=json.dumps(sop, ensure_ascii=False),
            scene_count=scene_count,
        )

    for attempt in range(config.MAX_RETRY + 1):
        try:
            response = model.generate_content(user_prompt)
            if not response.candidates or not response.candidates[0].content.parts:
                finish = getattr(response.candidates[0], "finish_reason", "unknown") if response.candidates else "no_candidates"
                raise RuntimeError(f"Gemini returned no content (finish_reason={finish})")
            text = response.text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except Exception as exc:
            if attempt == config.MAX_RETRY:
                raise RuntimeError(f"Script generation failed: {exc}") from exc
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_script_gen.py -v
```

Expected: 2 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add pipeline/script_gen.py tests/test_script_gen.py
git commit -m "feat: script generator — Gemini 3-act structure"
```

---

## Task 7: Scene Splitter

**Files:**
- Create: `pipeline/scene_splitter.py`
- Create: `tests/test_scene_splitter.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_scene_splitter.py
import json
import math
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import pytest
from pipeline.scene_splitter import split_scenes
from models.scene_manifest import SceneStatus

FAKE_SCRIPT = [
    {
        "scene_id": "S01", "act": "hook",
        "narration_ko": "안전모를 착용하세요.",
        "image_prompt": "construction site", "motion_prompt": "pan left",
        "camera": "wide", "mood": "calm", "on_screen_text": None,
    },
    {
        "scene_id": "S02", "act": "conflict",
        "narration_ko": "아웃리거를 완전히 전개하지 않으면 장비가 전도될 수 있습니다. 반드시 확인하세요.",
        "image_prompt": "truck tilting", "motion_prompt": "tilt slow",
        "camera": "low angle", "mood": "tense", "on_screen_text": None,
    },
]


def test_split_scenes_creates_manifest_and_audio(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()

    with patch("pipeline.scene_splitter.synthesize") as mock_tts:
        # S01: 5.0s → ceil = 5 → no split
        # S02: 9.2s → ceil = 10 → split into S02a (8s) + S02b (2s) — 2 chunks
        mock_tts.side_effect = [
            (b"AUDIO01", 5.0),
            (b"AUDIO02", 9.2),
        ]
        with patch("pipeline.scene_splitter._split_audio_file") as mock_split:
            manifest = split_scenes(
                script=FAKE_SCRIPT,
                workspace=workspace,
                video_style="hybrid",
                sop_title="테스트 SOP",
                duration=180,
            )

    manifest_path = workspace / "manifest.json"
    assert manifest_path.exists()
    # S01 unchanged, S02 → S02a + S02b
    scene_ids = [s.scene_id for s in manifest.scenes]
    assert "S01" in scene_ids
    assert "S02a" in scene_ids
    assert "S02b" in scene_ids
    assert "S02" not in scene_ids
    # provider + voice frozen
    assert manifest.tts_provider == "google"
    assert manifest.tts_voice is not None
    # _split_audio_file called TWICE: once for S02a (length=8), once for S02b (length=None)
    assert mock_split.call_count == 2
    calls = mock_split.call_args_list
    assert calls[0].kwargs["start"] == 0
    assert calls[0].kwargs["length"] == 8
    assert calls[1].kwargs["start"] == 8
    assert calls[1].kwargs["length"] is None


def test_split_scenes_no_subsplit_needed(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    single_scene = [FAKE_SCRIPT[0]]

    with patch("pipeline.scene_splitter.synthesize") as mock_tts:
        mock_tts.return_value = (b"AUDIO", 5.0)
        manifest = split_scenes(
            script=single_scene,
            workspace=workspace,
            video_style="hybrid",
            sop_title="테스트 SOP",
            duration=180,
        )

    assert len(manifest.scenes) == 1
    assert manifest.scenes[0].duration_sec == math.ceil(5.0)  # no +1 padding
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_scene_splitter.py -v
```

Expected: `ImportError: No module named 'pipeline.scene_splitter'`

- [ ] **Step 3: Write `pipeline/scene_splitter.py`**

```python
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

        # Freeze provider/voice after first successful call
        if tts_provider is None:
            tts_provider = provider
            tts_voice = voice

        duration_sec = math.ceil(dur_sec)  # no +1 padding — avoids spurious splits

        if duration_sec <= 8:
            scenes.append(_make_scene(raw, scene_id, duration_sec))
        else:
            # N-way split: every chunk is <= 8s; suffix = 'a', 'b', 'c', ...
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_scene_splitter.py -v
```

Expected: 2 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add pipeline/scene_splitter.py tests/test_scene_splitter.py
git commit -m "feat: scene splitter — TTS-first duration, sub-scene splitting, manifest.json"
```

---

## Task 8: Image Generator

**Files:**
- Create: `pipeline/image_gen.py`
- Create: `tests/test_image_gen.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_image_gen.py
import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from pipeline.image_gen import generate_images
from models.scene_manifest import Scene, SceneManifest, SceneStatus


def _make_manifest(tmp_path: Path) -> SceneManifest:
    return SceneManifest(
        sop_title="테스트", total_duration_sec=8,
        video_style="hybrid", tts_provider="google", tts_voice="ko-KR-Wavenet-B",
        scenes=[
            Scene(
                scene_id="S01", act="hook", duration_sec=8,
                status=SceneStatus.audio_ready,
                narration_ko="나레이션",
                image_prompt="Korean construction site, worker",
                motion_prompt="pan left", camera="wide", mood="tense",
            )
        ],
    )


def test_generate_images_saves_png_and_updates_status(tmp_path):
    manifest = _make_manifest(tmp_path)
    workspace = tmp_path / "ws"
    (workspace / "images").mkdir(parents=True)

    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50

    with patch("pipeline.image_gen.fal_client.subscribe") as mock_sub, \
         patch("pipeline.image_gen.httpx.get") as mock_get:
        mock_sub.return_value = {"images": [{"url": "https://fal.ai/fake.png"}]}
        mock_resp = MagicMock()
        mock_resp.content = fake_png
        mock_get.return_value = mock_resp

        updated = generate_images(manifest=manifest, workspace=workspace)

    img_path = workspace / "images" / "S01.png"
    assert img_path.exists()
    assert img_path.read_bytes() == fake_png
    assert updated.scenes[0].status == SceneStatus.image_ready


def test_generate_images_skips_scene_after_two_failures(tmp_path):
    manifest = _make_manifest(tmp_path)
    workspace = tmp_path / "ws"
    (workspace / "images").mkdir(parents=True)

    with patch("pipeline.image_gen.fal_client.subscribe", side_effect=RuntimeError("API error")):
        updated = generate_images(manifest=manifest, workspace=workspace)

    assert updated.scenes[0].status == SceneStatus.skipped
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_image_gen.py -v
```

Expected: `ImportError: No module named 'pipeline.image_gen'`

- [ ] **Step 3: Write `pipeline/image_gen.py`**

```python
from __future__ import annotations
import json
from pathlib import Path

import fal_client
import httpx
from rich.console import Console

import config
from models.scene_manifest import SceneManifest, SceneStatus

console = Console()


def generate_images(manifest: SceneManifest, workspace: Path) -> SceneManifest:
    images_dir = workspace / "images"
    images_dir.mkdir(parents=True, exist_ok=True)

    model = (
        "fal-ai/flux/dev/image-to-image"
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
        # Only process audio_ready (and pending if explicitly added to workspace)

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
            result = fal_client.subscribe(
                model,
                arguments={
                    "prompt": prompt,
                    "image_size": "landscape_16_9",
                    "num_inference_steps": 4,
                    "num_images": 1,
                    "enable_safety_checker": False,
                },
                with_logs=False,
            )
            image_url = result["images"][0]["url"]
            response = httpx.get(image_url, timeout=30)
            response.raise_for_status()
            out_path.write_bytes(response.content)
            return True
        except Exception as exc:
            if attempt == config.MAX_RETRY:
                console.print(f"[red]Image gen error: {exc}[/red]")
                return False
    return False
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_image_gen.py -v
```

Expected: 2 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add pipeline/image_gen.py tests/test_image_gen.py
git commit -m "feat: image generator — FLUX.1-schnell via fal-client, retry + skip on failure"
```

---

## Task 9: Video Generator

**Files:**
- Create: `pipeline/video_gen.py`
- Create: `tests/test_video_gen.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_video_gen.py
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
from pipeline.video_gen import generate_videos
from models.scene_manifest import Scene, SceneManifest, SceneStatus


def _make_manifest_with_image(tmp_path: Path) -> tuple[SceneManifest, Path]:
    workspace = tmp_path / "ws"
    (workspace / "images").mkdir(parents=True)
    (workspace / "clips").mkdir(parents=True)
    img_path = workspace / "images" / "S01.png"
    img_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

    manifest = SceneManifest(
        sop_title="테스트", total_duration_sec=8,
        video_style="hybrid", tts_provider="google", tts_voice="ko-KR-Wavenet-B",
        scenes=[
            Scene(
                scene_id="S01", act="hook", duration_sec=8,
                status=SceneStatus.image_ready,
                narration_ko="나레이션", image_prompt="construction",
                motion_prompt="slow pan", camera="wide", mood="tense",
            )
        ],
    )
    return manifest, workspace


def test_generate_videos_downloads_and_updates_status(tmp_path):
    manifest, workspace = _make_manifest_with_image(tmp_path)
    fake_mp4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 100

    with patch("pipeline.video_gen.fal_client.subscribe") as mock_sub, \
         patch("pipeline.video_gen.httpx.get") as mock_get, \
         patch("pipeline.video_gen._upload_image_to_fal", return_value="https://fal.ai/img.png"):
        mock_sub.return_value = {"video": {"url": "https://fal.ai/fake.mp4"}}
        mock_resp = MagicMock()
        mock_resp.content = fake_mp4
        mock_get.return_value = mock_resp

        updated = generate_videos(manifest=manifest, workspace=workspace)

    clip_path = workspace / "clips" / "S01.mp4"
    assert clip_path.exists()
    assert clip_path.read_bytes() == fake_mp4
    assert updated.scenes[0].status == SceneStatus.clip_ready


def test_generate_videos_skips_scene_after_two_failures(tmp_path):
    manifest, workspace = _make_manifest_with_image(tmp_path)

    with patch("pipeline.video_gen.fal_client.subscribe", side_effect=RuntimeError("Kling error")), \
         patch("pipeline.video_gen._upload_image_to_fal", return_value="https://fal.ai/img.png"):
        updated = generate_videos(manifest=manifest, workspace=workspace)

    assert updated.scenes[0].status == SceneStatus.skipped
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_video_gen.py -v
```

Expected: `ImportError: No module named 'pipeline.video_gen'`

- [ ] **Step 3: Write `pipeline/video_gen.py`**

```python
from __future__ import annotations
import base64
import os
from pathlib import Path

import fal_client
import httpx
from rich.console import Console

import config
from models.scene_manifest import SceneManifest, SceneStatus

console = Console()

COST_PER_SEC = 0.112
COST_WARN_THRESHOLD = 30.0


def generate_videos(manifest: SceneManifest, workspace: Path) -> SceneManifest:
    clips_dir = workspace / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    images_dir = workspace / "images"

    active_scenes = [s for s in manifest.scenes if s.status == SceneStatus.image_ready]
    total_sec = sum(s.duration_sec for s in active_scenes)
    estimated_cost = total_sec * COST_PER_SEC
    if estimated_cost > COST_WARN_THRESHOLD:
        console.print(
            f"[bold yellow]Warning: estimated Kling cost ${estimated_cost:.2f} (>{COST_WARN_THRESHOLD}).[/bold yellow]"
        )
        # FORCE_RUN=1 skips interactive prompt (use in tests / CI)
        if os.environ.get("FORCE_RUN") != "1":
            answer = input("Continue? [y/N] ").strip().lower()
            if answer != "y":
                raise SystemExit("Aborted by user.")

    for scene in manifest.scenes:
        if scene.status != SceneStatus.image_ready:
            continue

        img_path = images_dir / f"{scene.scene_id}.png"
        clip_path = clips_dir / f"{scene.scene_id}.mp4"

        # C3: upload is inside retry via _generate_with_retry — pass path, not URL
        success = _generate_with_retry(scene, img_path, clip_path)

        if success:
            scene.status = SceneStatus.clip_ready
        else:
            scene.status = SceneStatus.skipped
            console.print(f"[yellow]Warning: video gen failed for {scene.scene_id}, skipping[/yellow]")

        manifest.save(workspace)

    return manifest


def _generate_with_retry(scene, img_path: Path, clip_path: Path) -> bool:
    # C3: upload is inside the retry loop so upload failures are also retried
    for attempt in range(config.MAX_RETRY + 1):
        try:
            image_url = _upload_image_to_fal(img_path)
            result = fal_client.subscribe(
                config.DEFAULT_VIDEO_MODEL,
                arguments={
                    "prompt": scene.motion_prompt,
                    "image_url": image_url,
                    "duration": str(min(scene.duration_sec, 8)),
                    "aspect_ratio": "16:9",
                    "negative_prompt": "blur, distort, low quality, watermark",
                },
                with_logs=False,
            )
            video_url = result["video"]["url"]
            response = httpx.get(video_url, timeout=120)
            response.raise_for_status()
            clip_path.write_bytes(response.content)
            return True
        except Exception as exc:
            if attempt == config.MAX_RETRY:
                console.print(f"[red]Video gen error: {exc}[/red]")
                return False
    return False


def _upload_image_to_fal(img_path: Path) -> str:
    """Upload local image to fal storage, return public URL."""
    with open(img_path, "rb") as f:
        result = fal_client.upload(f.read(), content_type="image/png")
    return result
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_video_gen.py -v
```

Expected: 2 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add pipeline/video_gen.py tests/test_video_gen.py
git commit -m "feat: video generator — Kling 3.0 via fal-client, $30 cost gate, retry+skip"
```

---

## Task 10: Assembler

**Files:**
- Create: `pipeline/assembler.py`
- Create: `tests/test_assembler.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_assembler.py
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
    # _make_ready_manifest already sets status=clip_ready — do NOT downgrade
    manifest = _make_ready_manifest(workspace)

    fake_output = output_dir / "result.mp4"
    fake_output.write_bytes(b"\x00" * 10)

    with patch("pipeline.assembler.subprocess.run") as mock_run, \
         patch("pipeline.assembler._audio_duration", return_value=7.5), \
         patch("pipeline.assembler._final_output_path", return_value=fake_output):
        mock_run.return_value = MagicMock(returncode=0)
        result = assemble(manifest=manifest, workspace=workspace, output_dir=output_dir)

    assert result == fake_output
    assert mock_run.call_count >= 2  # normalize + merge at minimum


def test_assemble_raises_when_clip_missing(tmp_path):
    workspace = tmp_path / "ws"
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    manifest = _make_ready_manifest(workspace)
    # Remove the clip to trigger integrity check (scene is clip_ready but file missing)
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
        # No assemblable scenes → should raise or return gracefully
        with pytest.raises(AssemblyError, match="No assemblable scenes"):
            assemble(manifest=manifest, workspace=workspace, output_dir=output_dir)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_assembler.py -v
```

Expected: `ImportError: No module named 'pipeline.assembler'`

- [ ] **Step 3: Write `pipeline/assembler.py`**

```python
from __future__ import annotations
import subprocess
from datetime import datetime
from pathlib import Path

from rich.console import Console

from models.scene_manifest import SceneManifest, SceneStatus
from pipeline.tts import _audio_duration

console = Console()


class AssemblyError(Exception):
    pass


def assemble(manifest: SceneManifest, workspace: Path, output_dir: Path) -> Path:
    """Merge clips + audio per scene, then concatenate into final MP4.

    Resume-safe: per-scene merge (clip_ready→merged_ready) is checkpointed
    separately from final concat (merged_ready→assembled). On rerun, already-merged
    scenes are skipped.
    """
    # Include clip_ready (needs merge) and merged_ready (needs concat only) scenes
    assemblable = [
        s for s in manifest.scenes
        if s.status in (SceneStatus.clip_ready, SceneStatus.merged_ready)
    ]

    if not assemblable:
        raise AssemblyError("No assemblable scenes — all scenes were skipped or pending.")

    clips_dir = workspace / "clips"
    audio_dir = workspace / "audio"
    tmp_dir = workspace / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Pre-assembly integrity check for clip_ready scenes only
    for scene in assemblable:
        if scene.status != SceneStatus.clip_ready:
            continue
        clip_path = clips_dir / f"{scene.scene_id}.mp4"
        audio_path = audio_dir / f"{scene.scene_id}.mp3"
        if not clip_path.exists():
            raise AssemblyError(f"missing clip: {clip_path}")
        if not audio_path.exists():
            raise AssemblyError(f"missing audio: {audio_path}")

    # Step 1+2: Normalize + merge per scene (skip if already merged)
    for scene in assemblable:
        merged_path = tmp_dir / f"{scene.scene_id}_merged.mp4"
        if merged_path.exists():
            continue  # resume: already merged in a prior run

        clip_path = clips_dir / f"{scene.scene_id}.mp4"
        audio_path = audio_dir / f"{scene.scene_id}.mp3"
        norm_path = tmp_dir / f"{scene.scene_id}_norm.mp4"

        subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(clip_path),
                "-vf", "scale=1920:1080",
                "-r", "24",
                "-c:v", "libx264", "-preset", "fast",
                str(norm_path),
            ],
            check=True, capture_output=True,
        )
        audio_dur = _audio_duration(audio_path)
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(norm_path),
                "-i", str(audio_path),
                "-t", str(audio_dur),
                "-c:v", "copy", "-c:a", "aac",
                str(merged_path),
            ],
            check=True, capture_output=True,
        )
        # Checkpoint: mark merged_ready, persist before concat
        scene.status = SceneStatus.merged_ready
        manifest.save(workspace)

    # Step 3: Concatenate all merged files in manifest order
    merged_paths = [
        tmp_dir / f"{s.scene_id}_merged.mp4"
        for s in assemblable
    ]
    concat_list = tmp_dir / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.resolve()}'" for p in merged_paths),
        encoding="utf-8",
    )

    output_path = _final_output_path(manifest.sop_title, output_dir)
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            str(output_path),
        ],
        check=True, capture_output=True,
    )

    # Only mark assembled after concat succeeds
    for scene in assemblable:
        scene.status = SceneStatus.assembled
    manifest.save(workspace)

    console.print(f"[green]Output: {output_path}[/green]")
    return output_path


def _final_output_path(sop_title: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    safe_title = sop_title.replace(" ", "_").replace("/", "-")[:40]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return output_dir / f"{safe_title}_{timestamp}.mp4"
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_assembler.py -v
```

Expected: 3 tests PASSED.

- [ ] **Step 5: Commit**

```bash
git add pipeline/assembler.py tests/test_assembler.py
git commit -m "feat: assembler — normalize + merge + concat + integrity check"
```

---

## Task 11: CLI

**Files:**
- Create: `main.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_cli.py
import argparse
import pytest
from main import build_parser, parse_stage_range


def test_parse_full_pipeline():
    parser = build_parser()
    args = parser.parse_args(["--sop", "test.docx"])
    assert args.sop == "test.docx"
    assert args.duration == 180
    assert args.dry_run is False


def test_parse_stage_range():
    assert parse_stage_range("4-5") == (4, 5)
    assert parse_stage_range("3") == (3, 3)
    assert parse_stage_range("1-7") == (1, 7)


def test_parse_stage_range_invalid():
    with pytest.raises(ValueError, match="Invalid --stage"):
        parse_stage_range("8")

    with pytest.raises(ValueError, match="Invalid --stage"):
        parse_stage_range("0-4")


def test_parse_shortform():
    parser = build_parser()
    args = parser.parse_args(["--sop", "test.docx", "--duration", "30"])
    assert args.duration == 30


def test_parse_stage_with_run_id():
    parser = build_parser()
    args = parser.parse_args(["--stage", "4-5", "--run-id", "20260418-153201"])
    assert args.stage == "4-5"
    assert args.run_id == "20260418-153201"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_cli.py -v
```

Expected: `ImportError: No module named 'main'` or `cannot import name 'build_parser'`

- [ ] **Step 3: Write `main.py`**

```python
from __future__ import annotations
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console

import config
from models.scene_manifest import SceneManifest, SceneStatus
from pipeline.assembler import assemble, AssemblyError
from pipeline.image_gen import generate_images
from pipeline.scene_splitter import split_scenes
from pipeline.script_gen import generate_script
from pipeline.sop_parser import parse_sop, ParseError
from pipeline.tts import synthesize
from pipeline.video_gen import generate_videos

console = Console()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safety Training Video Auto-Generation Pipeline"
    )
    parser.add_argument("--sop", help="Path to SOP file (.docx or .pdf)")
    parser.add_argument(
        "--duration", type=int, default=config.DEFAULT_DURATION,
        help="Target duration in seconds (30 or 180, default: 180)"
    )
    parser.add_argument(
        "--stage", help="Stage range to run, e.g. '4-5' or '3'"
    )
    parser.add_argument(
        "--run-id", dest="run_id",
        help="Workspace run_id to resume (required with --stage, auto-detected if omitted)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show manifest without generating media"
    )
    return parser


def parse_stage_range(stage_str: str) -> tuple[int, int]:
    parts = stage_str.split("-")
    if len(parts) == 1:
        s = int(parts[0])
        start = end = s
    elif len(parts) == 2:
        start, end = int(parts[0]), int(parts[1])
    else:
        raise ValueError(f"Invalid --stage format: {stage_str}")
    if not (1 <= start <= 7 and 1 <= end <= 7 and start <= end):
        raise ValueError(f"Invalid --stage range: {stage_str} (valid: 1-7)")
    return start, end


def _resolve_run_id(run_id: str | None) -> str:
    if run_id:
        return run_id
    workspace = config.WORKSPACE_DIR
    if not workspace.exists():
        console.print("[red]No workspace found. Provide --run-id or run from Stage 1.[/red]")
        sys.exit(1)
    runs = sorted(workspace.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
    runs = [r for r in runs if r.is_dir()]
    if not runs:
        console.print("[red]No existing workspace run found.[/red]")
        sys.exit(1)
    latest = runs[0].name
    answer = input(f"Use latest run '{latest}'? [y/N] ").strip().lower()
    if answer != "y":
        sys.exit("Aborted.")
    return latest


def _load_manifest(workspace: Path) -> SceneManifest:
    manifest_path = workspace / "manifest.json"
    if not manifest_path.exists():
        console.print(f"[red]manifest.json not found in {workspace}[/red]")
        sys.exit(1)
    return SceneManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.stage:
        start, end = parse_stage_range(args.stage)
        run_id = _resolve_run_id(args.run_id)
        workspace = config.WORKSPACE_DIR / run_id
        manifest = _load_manifest(workspace)
        _run_stages(start, end, manifest=manifest, workspace=workspace, args=args)
        return

    if not args.sop:
        parser.error("--sop is required when not using --stage")

    sop_path = Path(args.sop)
    if not sop_path.exists():
        console.print(f"[red]SOP file not found: {sop_path}[/red]")
        sys.exit(1)

    run_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    workspace = config.WORKSPACE_DIR / run_id
    workspace.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    console.print(f"[bold green]Run ID: {run_id}[/bold green]")

    _run_stages(1, 7, sop_path=sop_path, workspace=workspace, args=args)


def _run_stages(
    start: int,
    end: int,
    workspace: Path,
    args: argparse.Namespace,
    sop_path: Path | None = None,
    manifest: SceneManifest | None = None,
) -> None:
    if start <= 1 <= end:
        console.rule("[bold]Stage 1: SOP Parser[/bold]")
        sop = parse_sop(sop_path, run_workspace=workspace)
    else:
        sop = json.loads((workspace / "sop.json").read_text(encoding="utf-8"))

    script: list[dict] | None = None
    if start <= 2 <= end:
        console.rule("[bold]Stage 2: Script Generator[/bold]")
        script = generate_script(sop=sop, duration=args.duration)

    if start <= 3 <= end:
        console.rule("[bold]Stage 3: Scene Splitter (+ TTS)[/bold]")
        if script is None:
            raise ValueError("Stage 3 requires stage 2. Use --stage 2-3 or run stage 2 first.")
        manifest = split_scenes(
            script=script,
            workspace=workspace,
            video_style="shortform" if args.duration <= 30 else "hybrid",
            sop_title=sop["sop_title"],
            duration=args.duration,
        )
        if args.dry_run:
            console.print(manifest.model_dump_json(indent=2))
            return

    if manifest is None:
        manifest = _load_manifest(workspace)

    if start <= 4 <= end:
        console.rule("[bold]Stage 4: Image Generator[/bold]")
        manifest = generate_images(manifest=manifest, workspace=workspace)

    if start <= 5 <= end:
        console.rule("[bold]Stage 5: Video Generator[/bold]")
        manifest = generate_videos(manifest=manifest, workspace=workspace)

    if start <= 6 <= end:
        console.rule("[bold]Stage 6: TTS (fill gaps)[/bold]")
        _run_tts_stage(manifest, workspace)

    if start <= 7 <= end:
        console.rule("[bold]Stage 7: Assembler[/bold]")
        output_path = assemble(
            manifest=manifest,
            workspace=workspace,
            output_dir=config.OUTPUT_DIR,
        )
        console.print(f"\n[bold green]Done! Output: {output_path}[/bold green]")


def _run_tts_stage(manifest: SceneManifest, workspace: Path) -> None:
    """Fill any missing audio files (standalone Stage 6 rerun)."""
    audio_dir = workspace / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    for scene in manifest.scenes:
        if scene.status == SceneStatus.skipped:
            continue
        audio_path = audio_dir / f"{scene.scene_id}.mp3"
        if audio_path.exists():
            console.print(f"[dim]Skip TTS {scene.scene_id} — already exists[/dim]")
            continue
        _, dur = synthesize(
            text=scene.narration_ko,
            provider=manifest.tts_provider or "google",
            voice=manifest.tts_voice or "ko-KR-Wavenet-B",
            output_path=audio_path,
        )
        # Guard: never downgrade clip_ready/assembled — they already have audio
        if scene.status not in (SceneStatus.clip_ready, SceneStatus.assembled):
            scene.status = SceneStatus.audio_ready
        (workspace / "manifest.json").write_text(
            manifest.model_dump_json(indent=2), encoding="utf-8"
        )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_cli.py -v
```

Expected: 5 tests PASSED.

- [ ] **Step 5: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: All tests PASSED. No failures.

- [ ] **Step 6: Verify CLI --help works**

```bash
uv run python main.py --help
```

Expected: Usage message showing `--sop`, `--duration`, `--stage`, `--run-id`, `--dry-run` options.

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_cli.py
git commit -m "feat: CLI — argparse, stage range, run-id resume, dry-run, full pipeline orchestration"
```

---

## Self-Review

### Spec Coverage Check

| Spec Requirement | Task |
|---|---|
| DOCX/PDF → SOP JSON | Task 5 |
| Gemini API (google-generativeai) | Task 5, 6 |
| TTS duration-first scene splitting | Task 7 |
| 8-sec sub-scene split + audio split | Task 7 |
| FLUX.1-schnell image gen | Task 8 |
| USE_FLUX_DEV flag | Task 8 (`config.USE_FLUX_DEV`) |
| Kling 3.0 video gen | Task 9 |
| $30 cost gate | Task 9 |
| Stage 7 normalize → merge → concat | Task 10 |
| Manifest status machine | Task 2, 7, 8, 9, 10 |
| Pre-assembly integrity check | Task 10 |
| TTS single-source-of-truth | Task 4, 7 |
| `--sop`, `--duration`, `--stage`, `--run-id`, `--dry-run` CLI | Task 11 |
| Auto-select latest workspace | Task 11 (`_resolve_run_id`) |
| `ParseError`, `AssemblyError` | Task 5, 10 |
| FFmpeg not found → exit with instructions | ✅ (`subprocess.run` raises `FileNotFoundError` on missing ffmpeg — add explicit check in assembler if needed) |
| Character consistency prefix | Task 3 (`prompts/scene_prompt.py`) |
| 3-act template / shortform template | Task 3 (`prompts/script_prompt.py`) |

**Gap:** FFmpeg not-found error handling. The assembler uses `subprocess.run(..., check=True)` which raises `FileNotFoundError` if `ffmpeg` isn't in PATH. Add explicit check at `assemble()` entry:

Add to the top of `pipeline/assembler.py`'s `assemble()` function:
```python
import shutil
if not shutil.which("ffmpeg"):
    raise SystemExit(
        "FFmpeg not found. Install it:\n"
        "  Windows: winget install Gyan.FFmpeg\n"
        "  Mac:     brew install ffmpeg\n"
        "  Linux:   sudo apt install ffmpeg"
    )
```

### Type Consistency Check
- `synthesize()` signature: `(text, provider, voice, output_path) -> (bytes, float)` — used consistently in `scene_splitter.py` Task 7 and `_run_tts_stage` Task 11.
- `generate_images(manifest, workspace)` — matches usage in `main.py`.
- `generate_videos(manifest, workspace)` — matches usage in `main.py`.
- `assemble(manifest, workspace, output_dir)` — matches usage in `main.py`.
- `SceneStatus` enum values used across all modules: consistent.
- `_audio_duration` imported from `pipeline.tts` in `assembler.py` — defined in Task 4.

All types consistent. ✅

---

Plan complete and saved to `docs/superpowers/plans/2026-04-18-safety-video-pipeline.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** — Fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
