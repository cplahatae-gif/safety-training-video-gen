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
