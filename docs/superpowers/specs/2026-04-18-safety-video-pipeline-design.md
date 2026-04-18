# Safety Training Video Auto-Generation Pipeline — Design Spec

**Date:** 2026-04-18
**Status:** Approved
**Project:** safety-training-video-gen

---

## Overview

A CLI tool that converts SOP documents (DOCX/PDF) into finished safety training videos (MP4 1080p) via a fully automated 7-stage pipeline. Designed for 삼표산업 SHE팀 internal PoC. Sensitive data excluded from PoC scope.

**Target output:**
- 30-second short-form (shortform safety point)
- Up to 3-minute hybrid (lecture narration + scenario B-roll)

---

## Architecture

```
Input: SOP file (DOCX/PDF)
         │
         ▼
[Stage 1] sop_parser        DOCX/PDF → structured JSON
         │
         ▼
[Stage 2] script_gen        Claude API → script JSON (narration + visual intent per scene)
         │
         ▼
[Stage 3] scene_splitter    Script → scene_manifest.json (8-sec chunks)
         │
         ▼
[Stage 4] image_gen         fal.ai FLUX.1 → keyframe images (one per scene)
         │
         ▼
[Stage 5] video_gen         Kling 3.0 image-to-video via fal.ai → scene .mp4 files
         │
         ▼
[Stage 6] tts               Google Cloud TTS (WaveNet) → per-scene narration .mp3
         │
         ▼
[Stage 7] assembler         FFmpeg → final .mp4 (video + audio merged, scenes concatenated)
         │
         ▼
Output: output/<sop_title>_<timestamp>.mp4
```

---

## Project Structure

```
safety-training-video-gen/
├── main.py                        # CLI entrypoint
├── pipeline/
│   ├── __init__.py
│   ├── sop_parser.py              # Stage 1
│   ├── script_gen.py              # Stage 2
│   ├── scene_splitter.py          # Stage 3
│   ├── image_gen.py               # Stage 4
│   ├── video_gen.py               # Stage 5
│   ├── tts.py                     # Stage 6
│   └── assembler.py               # Stage 7
├── prompts/
│   ├── script_prompt.py           # Claude prompts for script generation
│   └── scene_prompt.py            # Image/motion prompt templates
├── models/
│   └── scene_manifest.py          # Pydantic schema for scene_manifest.json
├── output/                        # Final MP4s
├── workspace/                     # Intermediate files (images, clips, audio)
│   └── <run_id>/
│       ├── sop.json
│       ├── manifest.json
│       ├── images/
│       ├── clips/
│       └── audio/
├── config.py                      # API keys, model names, defaults
├── .env.example
└── requirements.txt
```

---

## CLI Interface

```bash
# Full pipeline (default: 3-min hybrid)
python main.py --sop path/to/sop.docx

# Short-form (30 seconds)
python main.py --sop path/to/sop.docx --duration 30

# Run specific stages only (requires --run-id to resume existing workspace)
python main.py --stage 4-5 --run-id 20260418-153201

# Auto-select latest workspace (prompts for confirmation)
python main.py --stage 4-5

# Dry run (show manifest without generating media)
python main.py --sop path/to/sop.docx --dry-run
```

---

## Data Models

### SOP JSON (output of Stage 1)
```json
{
  "sop_title": "고소작업차 운용 표준 안전작업지침",
  "legal_basis": ["산업안전보건기준에 관한 규칙 제186조"],
  "hazards": [
    {"id": "H1", "name": "추락", "severity": "사망"}
  ],
  "procedure_steps": [
    {"step": 1, "action": "작업 전 점검", "key_rules": ["아웃리거 완전 전개"]}
  ],
  "target_audience": "중장비 운전자",
  "common_violations": ["안전대 미착용"]
}
```

### scene_manifest.json (output of Stage 3)
```json
{
  "sop_title": "고소작업차 운용 표준 안전작업지침",
  "total_duration_sec": 180,
  "video_style": "hybrid",
  "scenes": [
    {
      "scene_id": "S01",
      "act": "hook",
      "duration_sec": 8,
      "narration_ko": "아웃리거를 완전히 전개하지 않으면 이런 일이 생깁니다.",
      "image_prompt": "Korean construction site, aerial work platform truck, worker in Sampyo navy uniform with reflective stripes, white hard hat with Sampyo logo, morning light, wide shot",
      "motion_prompt": "truck slowly tilts to one side, worker grabs handrail, slow motion",
      "camera": "low angle, slow dolly in",
      "mood": "tense",
      "on_screen_text": null
    }
  ]
}
```

---

## Stage Specifications

### Stage 1: SOP Parser (`sop_parser.py`)
- **Input:** .docx or .pdf file path
- **Output:** `workspace/<run_id>/sop.json`
- **Libraries:** `python-docx` for DOCX, `pdfplumber` for PDF
- **Logic:** Extract text → Claude API call to structure into SOP JSON schema
- **Error:** Raise `ParseError` if document is unreadable or schema validation fails

### Stage 2: Script Generator (`script_gen.py`)
- **Input:** `sop.json`, `duration` (30 or 180 sec)
- **Output:** Script dict (narration + visual intent, per scene)
- **Model:** `claude-sonnet-4-6` with prompt caching on system prompt
- **Template:** 3-act structure (hook / conflict+consequence / resolution+rules) for 3-min; single-point for 30-sec
- **Output language:** Korean narration, English image prompts

### Stage 3: Scene Splitter (`scene_splitter.py`)
- **Input:** Script dict
- **Output:** `workspace/<run_id>/manifest.json`
- **Logic:** TTS duration-first approach — call `tts.synthesize()` per scene first, measure audio duration, set `duration_sec = ceil(audio_duration) + 1`
- **8-second limit handling:** If `duration_sec > 8`, split into sub-scenes: `[S03a (8s), S03b (remainder)]`. Same image, motion prompt continues. Kling called once per sub-scene.
- **tts.py interface:** Must expose `synthesize(text) -> (audio_bytes, duration_sec)` callable from both Stage 3 and standalone Stage 6

### Stage 4: Image Generator (`image_gen.py`)
- **Input:** `manifest.json`
- **Output:** `workspace/<run_id>/images/S<N>.png`
- **API:** fal.ai FLUX.1-schnell (`fal-ai/flux/schnell`, ~$0.003/image) — text-to-image only
- **Character consistency strategy:** FLUX.1-schnell does NOT support reference images. Use "prompt consistency" — prepend a fixed character description block to every image prompt: `"Korean male worker, Sampyo navy blue uniform, reflective stripes, white hard hat with Sampyo logo, [scene-specific content]"`. For higher consistency, switch to `fal-ai/flux/dev/image-to-image` (IP-Adapter, ~$0.025/image) — configurable via `USE_FLUX_DEV=true` env flag.
- **Retry:** 1 automatic retry on failure; skip scene and log warning after 2 failures

### Stage 5: Video Generator (`video_gen.py`)
- **Input:** `images/S<N>.png` + `manifest.json`
- **Output:** `workspace/<run_id>/clips/S<N>.mp4`
- **API:** fal.ai Kling 3.0 image-to-video (`fal-ai/kling-video/v3/pro/image-to-video`, ~$0.112/sec, audio OFF)
- **Mode:** No audio (TTS added separately in Stage 7)
- **Retry:** 1 automatic retry; Kling has ~10% failure rate on complex motion prompts
- **Cost gate:** Warn if estimated cost > $30 before proceeding

### Stage 6: TTS (`tts.py`)
- **Input:** `narration_ko` per scene
- **Output:** `workspace/<run_id>/audio/S<N>.mp3`
- **Primary:** Google Cloud TTS WaveNet (language: `ko-KR`, voice: `ko-KR-Wavenet-A/B/C`)
- **Fallback:** ElevenLabs Multilingual v2 if Google Cloud TTS unavailable
- **Cost:** WaveNet ~$0.016/1K chars (월 100만자 무료 → 3분 영상 약 1,500자 기준 약 666편까지 무료)
- **Note:** Called during Stage 3 to determine scene durations

### Stage 7: Assembler (`assembler.py`)
- **Input:** `clips/S<N>.mp4` + `audio/S<N>.mp3`
- **Output:** `output/<sop_title>_<timestamp>.mp4`
- **Tool:** FFmpeg (must be in PATH)
- **Steps:**
  1. Normalize each clip: `ffmpeg -i clip.mp4 -vf scale=1920:1080 -r 24 -c:v libx264 normalized.mp4`
  2. Merge clip + audio with explicit duration: `ffmpeg -i normalized.mp4 -i audio.mp3 -t {audio_duration} merged.mp4` (avoid `-shortest` — clips may be shorter than audio for sub-scenes)
  3. Concatenate all merged clips via concat demuxer
  4. Apply fade-in/fade-out between scenes (0.3s crossfade)

---

## Configuration (`config.py` / `.env`)

```
ANTHROPIC_API_KEY=
FAL_KEY=
GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json   # Google Cloud TTS
ELEVENLABS_API_KEY=       # fallback TTS

# Defaults
DEFAULT_IMAGE_MODEL=fal-ai/flux/schnell
DEFAULT_VIDEO_MODEL=fal-ai/kling-video/v3/pro/image-to-video
USE_FLUX_DEV=false          # set true for IP-Adapter reference image (better character consistency)
DEFAULT_DURATION=180
MAX_RETRY=1
WORKSPACE_DIR=./workspace
OUTPUT_DIR=./output
```

---

## Error Handling

| Scenario | Behavior |
|---|---|
| SOP parse failure | Raise `ParseError`, exit with message |
| Claude API timeout | Retry once, then exit |
| Kling generation failure | Retry once, log warning, continue with remaining scenes |
| FFmpeg not found | Exit with install instructions |
| Estimated cost > $30 | Prompt user to confirm before proceeding |

---

## Out of Scope (PoC)

- HWP file support (Phase 2)
- HeyGen/Synthesia avatar layer (Phase 2)
- SCORM/LMS export (Phase 2)
- n8n automation trigger (Phase 2)
- Sensitive internal data (삼표 accident photos, employee images)

---

## Dependencies

```
anthropic>=0.90.0
python-docx
pdfplumber
fal-client                  # fal.ai SDK (migration to `fal` pkg in progress — check fal.ai docs)
google-cloud-texttospeech
pydantic>=2.0
python-ffmpeg               # replaces abandoned ffmpeg-python; same import API
python-dotenv
rich
```

**Python version:** 3.12 recommended.
**Package manager:** uv (`uv add`, `uv.lock`).
**FFmpeg binary:** `brew install ffmpeg` — verify arm64 path (`which ffmpeg` → `/opt/homebrew/bin/ffmpeg`).

---

## Success Criteria

- [ ] SOP DOCX 1장 → MP4 자동 생성 end-to-end 완료
- [ ] 씬 간 캐릭터(안전모·조끼) 시각적 일관성 유지
- [ ] 편당 총비용 $20 이하 (3분 기준)
- [ ] `--stage` 옵션으로 특정 단계 단독 재실행 가능
- [ ] 실패한 씬은 건너뛰고 나머지로 영상 완성 가능
