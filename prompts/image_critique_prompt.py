"""Vision self-critique prompt for generated scene images.

Used by ImageAgent to evaluate FLUX output and decide whether to retry.
Specifically watches for FLUX failure modes:
- broken anatomy (missing neck, floating limbs, extra fingers)
- domain mismatch (industrial outfit in lab scene)
- composition issues (split screen, multiple panels)
- equipment mismatch
"""

IMAGE_CRITIQUE_PROMPT = """\
당신은 안전교육 영상의 이미지 품질 평가자입니다.
이 이미지는 "{equipment_type}" 관련 안전교육 영상의 "{act}" 씬입니다.
도메인: {domain}
씬 설명: {image_prompt}

다음 항목을 0-10으로 채점하고 JSON으로만 응답하세요 (다른 텍스트 없이):
{{
  "anatomy": <0-10>,
  "domain_match": <0-10>,
  "no_split_screen": <0-10>,
  "equipment_match": <0-10>,
  "composition": <0-10>,
  "main_issue": "가장 큰 문제 한 줄 (모두 통과면 null)",
  "retry_hint": "재생성 시 강조할 키워드 (모두 통과면 null)"
}}

채점 기준 (각 항목 7점 미만이면 재생성 필요):

1. **anatomy** (신체 정상성):
   - 10: 모든 인물의 목/팔/다리/손이 정상
   - 5: 약간 이상 (얼굴 흐림 등)
   - 0: 목 없는 사람, 떠있는 옷, 손가락 6개 등 명백한 결함

2. **domain_match** (도메인 일치):
   - 10: "{domain}"에 맞는 복장과 환경
   - 5: 일부 어색함
   - 0: 완전 미스매치 (lab에 작업복+안전모 등)

3. **no_split_screen** (단일 구도):
   - 10: 단일 카메라 단일 장면
   - 0: 분할화면, 콜라주, 사이드바이사이드, before/after

4. **equipment_match** (장비 일치):
   - 10: "{equipment_type}"이 명확히 보임
   - 5: 비슷한 장비
   - 0: 다른 장비, 추상적

5. **composition** (구도 품질):
   - 10: 선명, 안정적, 자연스러움
   - 5: 일부 흐림 또는 어색
   - 0: 흐릿하거나 이상한 비율
"""


REFINE_PROMPT_HINT_PROMPT = """\
원래 image_prompt:
{original_prompt}

이전 이미지에서 발견된 문제:
{issues}

문제를 해결하기 위해 image_prompt를 어떻게 수정해야 할까요?
다음 JSON 형식으로만 응답:
{{
  "refined_prompt": "수정된 영문 image_prompt (단일 연속 샷, 분할화면 절대 금지)",
  "what_changed": "어떤 부분을 수정했는지 한 줄"
}}

수정 원칙:
- 기존 핵심 의도 유지
- 문제 해결을 위한 키워드 추가/제거
- "single continuous shot, no split screen" 명시
- 신체 결함 방지: "anatomically correct, complete person"
- 도메인 미스매치 방지: 도메인 명시 키워드 추가
"""
