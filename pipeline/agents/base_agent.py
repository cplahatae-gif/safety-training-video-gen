"""Base classes and utilities for pipeline agents.

Agents follow a research-backed pattern (arxiv 2512.16954):
1. Generate output (LLM or model call)
2. Self-critique (Gemini eval)
3. Refine if score < threshold (max retries)
4. Return best result with score

This module provides shared infrastructure:
- Gemini client factory
- JSON parsing with markdown fence stripping
- Retry/backoff helpers
"""
from __future__ import annotations
import json
import re
import time
from dataclasses import dataclass
from typing import Any

from google import genai
from rich.console import Console

import config

console = Console()


# ─── Configuration ────────────────────────────────────────────────────────────

PASS_THRESHOLD = 7.0  # Score below this triggers refine
MAX_REFINE_ATTEMPTS = 2  # 1 initial + 1 retry by default

# Gemini throttle handling
_THROTTLE_RESET_RE = re.compile(r"resets in\s*~?(\d+)s")


def gemini_client() -> genai.Client:
    """Shared Gemini client factory."""
    return genai.Client(api_key=config.GEMINI_API_KEY)


# ─── JSON parsing ─────────────────────────────────────────────────────────────


def parse_json_response(text: str) -> Any:
    """Strip markdown code fences and parse JSON. Handles Gemini's ```json wrappers."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return json.loads(text)


# ─── Throttle / retry ─────────────────────────────────────────────────────────


def throttle_sleep_seconds(exc: Exception) -> int | None:
    """Detect Gemini 429 throttle errors and extract reset time."""
    msg = str(exc)
    if "429" not in msg and "throttled" not in msg.lower() and "RESOURCE_EXHAUSTED" not in msg:
        return None
    match = _THROTTLE_RESET_RE.search(msg)
    return (int(match.group(1)) + 1) if match else 10


def call_gemini_with_retry(
    prompt: str,
    *,
    model: str | None = None,
    max_retries: int = 3,
    contents: list | None = None,
) -> str:
    """Call Gemini with retry on 429 throttle. Returns response.text."""
    client = gemini_client()
    model = model or config.GEMINI_MODEL
    payload = contents if contents is not None else prompt

    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(model=model, contents=payload)
            return response.text
        except Exception as exc:
            last_exc = exc
            sleep_s = throttle_sleep_seconds(exc)
            if sleep_s is not None and attempt < max_retries:
                console.print(f"[dim]Gemini 429 - sleep {sleep_s}s (retry {attempt + 1}/{max_retries})[/dim]")
                time.sleep(sleep_s)
                continue
            if attempt == max_retries:
                break
    raise RuntimeError(f"Gemini call failed after {max_retries + 1} attempts: {last_exc}")


# ─── Critique result ──────────────────────────────────────────────────────────


@dataclass
class CritiqueResult:
    """Output of a self-critique step."""
    score: float
    issues: list[str]
    raw: dict  # Full Gemini response for debugging
    passed: bool

    @classmethod
    def from_dict(cls, data: dict, threshold: float = PASS_THRESHOLD) -> "CritiqueResult":
        """Build from Gemini eval JSON. Expects 'score' or computes from sub-scores."""
        score = data.get("score")
        if score is None:
            # Compute average from numeric fields (excluding meta)
            meta_keys = {"issues", "reason", "score", "feedback"}
            nums = [v for k, v in data.items() if k not in meta_keys and isinstance(v, (int, float))]
            score = sum(nums) / len(nums) if nums else 0.0
        score = float(score)
        issues = data.get("issues", [])
        if isinstance(issues, str):
            issues = [issues]
        if not isinstance(issues, list):
            issues = []
        return cls(score=score, issues=issues, raw=data, passed=score >= threshold)


# ─── BaseAgent ────────────────────────────────────────────────────────────────


class BaseAgent:
    """Subclass to implement an agent with generate/critique/refine loop.

    Subclass interface:
        _generate(input) -> output
        _critique(output) -> CritiqueResult
        _refine(output, issues) -> output  (optional; default = re-generate)

    Public:
        run(input) -> (output, last_critique)
    """

    name: str = "base"
    threshold: float = PASS_THRESHOLD
    max_attempts: int = MAX_REFINE_ATTEMPTS

    def _generate(self, input_data: Any) -> Any:
        raise NotImplementedError

    def _critique(self, output: Any) -> CritiqueResult:
        # Default: no critique, always pass
        return CritiqueResult(score=10.0, issues=[], raw={}, passed=True)

    def _refine(self, output: Any, issues: list[str]) -> Any:
        # Default: just re-generate from scratch
        return self._generate(output)

    def run(self, input_data: Any) -> tuple[Any, CritiqueResult]:
        """Generate -> critique -> refine loop. Returns best (output, critique)."""
        output = self._generate(input_data)
        critique = self._critique(output)
        attempts = 1

        best_output, best_critique = output, critique

        while not critique.passed and attempts < self.max_attempts:
            console.print(
                f"[yellow]{self.name}: score {critique.score:.1f}/10 < {self.threshold} — refining (attempt {attempts + 1}/{self.max_attempts})[/yellow]"
            )
            for issue in critique.issues[:3]:
                console.print(f"  - {issue}")
            output = self._refine(output, critique.issues)
            critique = self._critique(output)
            attempts += 1
            if critique.score > best_critique.score:
                best_output, best_critique = output, critique

        if best_critique.passed:
            console.print(f"[green]{self.name}: passed ({best_critique.score:.1f}/10)[/green]")
        else:
            console.print(
                f"[yellow]{self.name}: best score {best_critique.score:.1f}/10 < {self.threshold} after {attempts} attempts. Returning best.[/yellow]"
            )

        return best_output, best_critique
