import json
from pathlib import Path
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"

@pytest.fixture
def sample_sop() -> dict:
    return json.loads((FIXTURES_DIR / "sample_sop.json").read_text(encoding="utf-8"))
