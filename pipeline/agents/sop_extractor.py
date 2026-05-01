"""SOP Deep Extractor + Domain Detector.

Pulls richer information from a parsed SOP:
- specific_hazards (with numbers/thresholds)
- specific_procedures (step-by-step actions)
- equipment_details (model numbers, specs)
- injury_types (eye damage, burns, etc.)
- thresholds (MPE, dB, percentages)

Also detects domain (industrial / lab / medical / chemical / construction / general)
which drives character prefix selection in image generation.
"""
from __future__ import annotations
import json

from rich.console import Console

from models.scene_manifest import DeepExtract
from pipeline.agents.base_agent import call_gemini_with_retry, parse_json_response

console = Console()


_DEEP_EXTRACT_PROMPT = """\
다음 안전작업지침(SOP)에서 영상 시나리오 작성에 필요한 **구체적이고 정량적인 정보**를 추출하세요.
슬로건이나 일반 표현은 제외하고, **수치·등급·모델명·구체 절차**만 추출합니다.

SOP 내용:
{sop_json}

다음 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{{
  "specific_hazards": [
    "구체적 위험 1 (수치/원인 포함, 예: '0.5초 노출로 망막 영구손상')",
    "구체적 위험 2"
  ],
  "specific_procedures": [
    "구체적 절차 1 (단계 포함, 예: '아웃리거 4개를 30도 각도로 완전 전개 후 수평 확인')",
    "구체적 절차 2"
  ],
  "equipment_details": [
    "장비 디테일 (모델명·사양 포함, 예: 'Spectra Physics Spitfire, Class 4, 800nm 펄스')"
  ],
  "injury_types": [
    "구체적 부상 유형 (예: '망막 화상', '각막 영구손상', '2도 화상')"
  ],
  "thresholds": [
    "정량 기준 (예: 'MPE 0.5 J/cm²', '소음 85dB 8시간', 'OD 5+ 보호안경')"
  ]
}}

규칙:
- 슬로건 금지 ("안전이 최우선" 같은 것)
- 빈 배열도 가능 (해당 정보가 SOP에 없으면)
- 추측 금지: SOP에 명시된 내용만
- 한국어로 작성
"""


_DOMAIN_DETECT_PROMPT = """\
다음 SOP의 작업 환경/도메인을 판별하세요.

SOP 제목: {sop_title}
대상자: {target_audience}
주요 위험: {hazards}
장비: {equipment_type}

다음 6개 중 하나로만 응답하세요 (JSON):
{{"domain": "industrial" | "lab" | "medical" | "chemical" | "construction" | "general"}}

판별 기준:
- industrial: 제조업·공장·생산라인 작업
- lab: 연구실·실험실 (대학·연구기관·R&D)
- medical: 병원·의료시설·간호 작업
- chemical: 화학물질·유해물질 취급 (도색·세척·실험 외)
- construction: 건설현장·공사·중장비
- general: 위 카테고리에 명확히 속하지 않으면

작업복 톤이 다른지를 기준으로 판단하세요:
- lab → 가운, 보호안경
- industrial → 작업복, 안전모
- medical → 스크럽
- chemical → 화학복, 마스크
- construction → 안전모, 반사조끼
"""


def detect_domain(sop: dict) -> str:
    """Detect work domain from SOP. Returns one of: industrial/lab/medical/chemical/construction/general."""
    hazards_summary = ", ".join(h.get("name", "") for h in sop.get("hazards", [])[:5])
    prompt = _DOMAIN_DETECT_PROMPT.format(
        sop_title=sop.get("sop_title", ""),
        target_audience=sop.get("target_audience", ""),
        hazards=hazards_summary,
        equipment_type=sop.get("equipment_type") or "(미기재)",
    )
    try:
        text = call_gemini_with_retry(prompt)
        result = parse_json_response(text)
        domain = result.get("domain", "general")
        if domain not in ("industrial", "lab", "medical", "chemical", "construction", "general"):
            console.print(f"[yellow]Unknown domain '{domain}' — defaulting to general[/yellow]")
            return "general"
        console.print(f"[dim]Domain detected: {domain}[/dim]")
        return domain
    except Exception as exc:
        console.print(f"[yellow]Domain detection failed ({exc}) — defaulting to general[/yellow]")
        return "general"


def extract_deep_info(sop: dict) -> DeepExtract:
    """Extract specific/quantitative safety info from SOP. Returns empty DeepExtract on failure."""
    sop_json = json.dumps(sop, ensure_ascii=False, indent=2)
    prompt = _DEEP_EXTRACT_PROMPT.format(sop_json=sop_json)
    try:
        text = call_gemini_with_retry(prompt)
        result = parse_json_response(text)
        return DeepExtract(
            specific_hazards=result.get("specific_hazards", []),
            specific_procedures=result.get("specific_procedures", []),
            equipment_details=result.get("equipment_details", []),
            injury_types=result.get("injury_types", []),
            thresholds=result.get("thresholds", []),
        )
    except Exception as exc:
        console.print(f"[yellow]Deep extraction failed ({exc}) — using empty extract[/yellow]")
        return DeepExtract()


def enrich_sop(sop: dict) -> dict:
    """Add domain + deep_extract fields to SOP dict in-place. Returns the same dict."""
    if "domain" not in sop or sop.get("domain") in (None, "general", ""):
        sop["domain"] = detect_domain(sop)
    if "deep_extract" not in sop or sop.get("deep_extract") is None:
        sop["deep_extract"] = extract_deep_info(sop).model_dump()
    return sop
