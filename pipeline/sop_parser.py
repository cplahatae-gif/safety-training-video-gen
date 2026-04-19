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
