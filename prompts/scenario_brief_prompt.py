"""Story brief prompt — generates 1-paragraph narrative arc before scene-level JSON.

Following arxiv 2512.16954 plan-then-generate pattern: produce a high-level
narrative skeleton first, then expand into structured scenes.
"""

BRIEF_PROMPT = """\
당신은 안전교육 영상 시나리오 작가입니다.
아래 SOP 정보를 바탕으로 {duration}초 영상의 **스토리 brief**를 작성합니다.

[SOP 핵심 정보]
- 제목: {sop_title}
- 도메인: {domain}
- 장비: {equipment_type}
- 대상: {target_audience}

[구체적 위험 (수치 포함)]
{specific_hazards}

[구체적 절차]
{specific_procedures}

[구체적 부상 유형]
{injury_types}

[정량 기준]
{thresholds}

---

요구사항:
- **5-7문장의 한 단락 줄글** (한국어)
- 5막 흐름: hook(주의 환기) → conflict(잘못된 행동) → consequence(구체 결과) → resolution(올바른 절차) → rules(핵심 수칙)
- **반드시 위에 추출된 구체 정보(수치·기준·부상)를 인용**
- 슬로건 금지: "안전이 최우선", "경각심을 갖자" 같은 일반 표현 사용 금지
- 시각적 묘사 포함: 어떤 장면이 보일지 1-2개 구체 묘사

출력 형식: 한 단락 줄글 (JSON 아님, 마크다운 헤더 아님). 그냥 텍스트 5-7문장.
"""
