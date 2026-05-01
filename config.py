import os
from pathlib import Path
from dotenv import load_dotenv

# Secrets live outside Drive to avoid leaking API keys via Drive sync.
_SECRETS_ENV = Path.home() / ".secrets" / "safety-video-gen" / ".env"
load_dotenv(_SECRETS_ENV if _SECRETS_ENV.exists() else None)

GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
REPLICATE_API_TOKEN: str = os.getenv("REPLICATE_API_TOKEN", "")
GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")

DEFAULT_IMAGE_MODEL: str = os.getenv("DEFAULT_IMAGE_MODEL", "black-forest-labs/flux-schnell")
REF_IMAGE_MODEL: str = os.getenv("REF_IMAGE_MODEL", "black-forest-labs/flux-1.1-pro")
DEFAULT_VIDEO_MODEL: str = os.getenv("DEFAULT_VIDEO_MODEL", "kwaivgi/kling-v2.5-turbo-pro")
USE_FLUX_DEV: bool = os.getenv("USE_FLUX_DEV", "false").lower() == "true"
DEFAULT_DURATION: int = int(os.getenv("DEFAULT_DURATION", "180"))
MAX_RETRY: int = int(os.getenv("MAX_RETRY", "1"))
WORKSPACE_DIR: Path = Path(os.getenv("WORKSPACE_DIR", "./workspace"))
OUTPUT_DIR: Path = Path(os.getenv("OUTPUT_DIR", "./output"))
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# Audio
TTS_SAMPLE_RATE: int = int(os.getenv("TTS_SAMPLE_RATE", "44100"))

# Subtitle burn-in
SUBTITLE_FONT_PATH: str = os.getenv(
    "SUBTITLE_FONT_PATH",
    r"C:\Windows\Fonts\malgun.ttf",
)

# BGM mixing
BGM_FILE: str = os.getenv("BGM_FILE", "")
BGM_VOLUME_DB: float = float(os.getenv("BGM_VOLUME_DB", "-18"))

# Outro
OUTRO_IMAGE: str = os.getenv("OUTRO_IMAGE", "")
OUTRO_NARRATION: str = os.getenv("OUTRO_NARRATION", "")
