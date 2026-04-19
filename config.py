import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
REPLICATE_API_TOKEN: str = os.getenv("REPLICATE_API_TOKEN", "")
GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")

DEFAULT_IMAGE_MODEL: str = os.getenv("DEFAULT_IMAGE_MODEL", "black-forest-labs/flux-schnell")
DEFAULT_VIDEO_MODEL: str = os.getenv("DEFAULT_VIDEO_MODEL", "kwaivgi/kling-v2.5-turbo-pro")
USE_FLUX_DEV: bool = os.getenv("USE_FLUX_DEV", "false").lower() == "true"
DEFAULT_DURATION: int = int(os.getenv("DEFAULT_DURATION", "180"))
MAX_RETRY: int = int(os.getenv("MAX_RETRY", "1"))
WORKSPACE_DIR: Path = Path(os.getenv("WORKSPACE_DIR", "./workspace"))
OUTPUT_DIR: Path = Path(os.getenv("OUTPUT_DIR", "./output"))
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
