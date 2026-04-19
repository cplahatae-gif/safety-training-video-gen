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
