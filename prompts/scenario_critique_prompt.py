"""Self-critique prompt for generated scenarios.

Evaluates:
- specificity: how concrete is the narration (numbers, procedures, injuries)?
- act_coverage: are all 5 acts present?
- equipment_lock: is the same equipment in every scene?
- safety_accuracy: does it teach actual safety knowledge?
- visual_clarity: are image prompts visualizable?
"""

CRITIQUE_PROMPT = """\
다음은 안전교육 영상 시나리오입니다. 5개 항목을 0-10으로 채점하고 JSON으로만 응답하세요.

[원본 SOP 핵심]
- 제목: {sop_title}
- 장비: {equipment_type}
- 도메인: {domain}
- 구체 위험: {specific_hazards}
- 구체 절차: {specific_procedures}

[평가 대상 시나리오]
{scenes_summary}

채점 기준 (0=최악, 10=완벽):

1. **specificity** (구체성):
   - 10: 모든 씬에 SOP의 수치/절차/부상이 인용됨
   - 5: 일부 씬에만 구체 정보 있음
   - 0: 모든 씬이 슬로건 ("안전이 중요", "주의하세요")

2. **act_coverage** (5막 충족):
   - 10: hook/conflict/consequence/resolution/rules 다 있음
   - 5: 1개 누락
   - 0: 2개 이상 누락

3. **equipment_lock** (장비 일관성):
   - 10: 모든 image_prompt에 동일 장비 명시
   - 0: 다른 장비가 등장

4. **safety_accuracy** (안전 정확도):
   - 10: SOP의 실제 절차/위험과 일치
   - 5: 부분 일치, 일부 부정확
   - 0: SOP와 무관하거나 위험한 정보

5. **visual_clarity** (시각 명료성):
   - 10: image_prompt가 그릴 수 있는 단일 장면
   - 5: 일부 모호하거나 추상적
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
