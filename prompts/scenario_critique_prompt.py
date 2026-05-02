"""Self-critique prompt for generated scenarios.

Evaluates:
- specificity: how concrete is the narration (numbers, procedures, injuries)?
- act_coverage: are all 5 acts present?
- equipment_lock: is the same equipment in every scene?
- safety_accuracy: does it teach actual safety knowledge?
- visual_clarity: are image prompts visualizable?
"""

CRITIQUE_PROMPT = """\
다음은 안전 캠페인 영상 시나리오(나레이션 없음, 비주얼+자막+BGM 기반)입니다.
5개 항목을 0-10으로 채점하고 JSON으로만 응답하세요.

**중요**: 이 영상은 의도적으로 나레이션을 사용하지 않습니다.
메시지 전달은 `image_prompt`(시각), `on_screen_text`(화면 자막), `bgm_keywords`(분위기) 3개로 이뤄집니다.
나레이션 없음을 점수 차감 사유로 삼지 마세요.

[원본 SOP 핵심]
- 제목: {sop_title}
- 장비: {equipment_type}
- 도메인: {domain}
- 구체 위험: {specific_hazards}
- 구체 절차: {specific_procedures}

[평가 대상 시나리오]
{scenes_summary}

채점 기준 (0=최악, 10=완벽):

1. **specificity** (구체성 — image_prompt와 on_screen_text 기준):
   - 10: 다수 씬의 image_prompt 또는 on_screen_text에 SOP 수치/절차/부상이 인용됨
   - 5: 일부 씬만 구체 정보
   - 0: 모든 씬이 슬로건/추상 표현

2. **act_coverage** (5막 충족):
   - 10: hook/conflict/consequence/resolution/rules 다 있음
   - 5: 1개 누락
   - 0: 2개 이상 누락

3. **equipment_lock** (장비 일관성):
   - 10: 모든 image_prompt에 동일/일관된 장비 명시
   - 0: 다른 장비가 등장

4. **safety_accuracy** (안전 정확도):
   - 10: SOP의 실제 절차/위험을 image_prompt/on_screen_text로 정확히 표현
   - 5: 부분 일치
   - 0: SOP와 무관하거나 잘못된 정보

5. **visual_clarity** (시각 명료성 — image_prompt 기준):
   - 10: image_prompt가 단일 연속 샷으로 그릴 수 있는 명확한 장면
   - 5: 일부 모호/추상
   - 0: 분할화면/콜라주/모순된 묘사

다음 JSON 형식으로만 출력:
{{
  "specificity": <0-10>,
  "act_coverage": <0-10>,
  "equipment_lock": <0-10>,
  "safety_accuracy": <0-10>,
  "visual_clarity": <0-10>,
  "issues": ["문제점 한 줄씩, 점수 7 미만 항목에 대해서만"]
}}
"""
