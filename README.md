# Safety Training Video Generator

Pipeline for turning SOP documents into short safety-training video assets.

The project parses a safety procedure document, creates a training script,
splits the script into scenes, generates image and motion prompts, produces
visual/audio assets, assembles a video, and can evaluate intermediate outputs.

## What It Does

- Parses SOP files from `.docx` or `.pdf`
- Creates a Korean safety-training script from the SOP
- Builds scene cards with narration, image prompts, motion prompts, on-screen
  text, and timing
- Generates scene images through Replicate image models
- Generates short video clips through a configured video model
- Synthesizes Korean narration through Google Cloud TTS or ElevenLabs
- Assembles clips, audio, subtitles, BGM, and outro assets into a final video
- Validates scenario, image, and clip stages with Gemini-based checks
- Supports stage-by-stage reruns for cost control and manual review

## Pipeline Stages

| Stage | Purpose |
| --- | --- |
| 1 | Parse and enrich SOP content |
| 2 | Generate training script |
| 3 | Split script into scene manifest |
| 4 | Generate scene images |
| 5 | Generate video clips |
| 6 | Generate narration audio |
| 7 | Assemble final video |

## Current Status

| Item | Status |
| --- | --- |
| Language | Python 3.12 |
| Package manager | uv |
| AI text/vision | Google Gemini |
| Image generation | Replicate image models |
| Video generation | Configurable Replicate video model |
| TTS | Google Cloud TTS or ElevenLabs |
| Tests | pytest |

## Requirements

- Python 3.12
- uv
- ffmpeg available on PATH
- Gemini API key
- Replicate API token
- Google Cloud TTS credentials or ElevenLabs API key if using paid TTS providers

## Setup

```bash
uv sync
cp .env.example .env
```

Fill the needed API keys in `.env`, or store them outside the repository and
load them through your shell environment.

## Run

Generate a full video from an SOP:

```bash
uv run python main.py --sop samples/고소작업차_아웃리거_점검.docx --duration 30
```

Run only a stage range:

```bash
uv run python main.py --stage 2-3 --run-id <run_id>
uv run python main.py --stage 4 --run-id <run_id>
uv run python main.py --stage 5-7 --run-id <run_id> --evaluate
```

Validate intermediate outputs:

```bash
uv run python scripts/validate_stage.py --stage 3 --workspace workspace/<run_id>
uv run python scripts/validate_stage.py --stage 4 --workspace workspace/<run_id>
uv run python scripts/validate_stage.py --stage 5 --workspace workspace/<run_id>
```

## Output Layout

```text
workspace/<run_id>/
├── sop.json
├── script.json
├── manifest.json
├── images/
├── clips/
└── audio/

output/
└── <final videos and evaluation reports>
```

## Configuration

Key environment variables:

| Variable | Purpose |
| --- | --- |
| `GEMINI_API_KEY` | Gemini text and vision validation |
| `REPLICATE_API_TOKEN` | Image and video generation |
| `GOOGLE_APPLICATION_CREDENTIALS` | Google Cloud TTS credentials |
| `ELEVENLABS_API_KEY` | Optional ElevenLabs TTS |
| `DEFAULT_IMAGE_MODEL` | Default image model |
| `DEFAULT_VIDEO_MODEL` | Default video model |
| `DEFAULT_DURATION` | Default video duration in seconds |
| `WORKSPACE_DIR` | Intermediate workspace directory |
| `OUTPUT_DIR` | Final output directory |

## Tests

```bash
uv run pytest
```

## Public Repository Notes

- Do not commit real API keys or service-account JSON files.
- Generated media can be expensive. Prefer stage-by-stage runs and manual review
  gates before clip generation.
- Review SOP samples before publishing derivative training content.

## License

MIT
