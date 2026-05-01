_FORBIDDEN_WORDS = (
    "split screen", "composite image", "montage", "side by side",
    "before/after collage", "before and after", "debris scattering",
    "glass shards", "explosion", "chaos",
)

_SYSTEM_BASE = """당신은 산업 안전교육 영상 대본 전문가입니다.
SOP 문서를 분석하여 현장 근로자를 위한 안전교육 영상 대본을 작성합니다.

[기본 규칙]
- 나레이션: 한국어로 작성, 짧고 명확하게 (씬당 1~3문장)
- 이미지 프롬프트: 영어로 작성, Stable Diffusion 스타일
- act 필드는 반드시 다음 중 하나의 소문자 영문 단어: hook | conflict | consequence | resolution | rules
- 5막 구조 필수: 반드시 hook, conflict, consequence, resolution, rules 각 1개 이상 포함
  - resolution 씬: 올바른 작업 절차를 실제로 수행하는 장면 (가장 비중 있게)

[이미지 프롬프트 제약 — 반드시 준수]
- 단일 연속 샷(single continuous shot)만 묘사. 절대 금지어: {forbidden}
- consequence 씬: 장비가 기울어지거나 경고 테이프, 낙하물 등 정적 위험 표시만 허용.
  폭발, 유리파편, 혼돈 장면 금지. 화면에는 30° 미만으로 기울어진 장비와 경고 테이프를 보여줄 것.
- resolution 씬: 작업자가 올바른 절차를 차분하게 실행하는 장면. 분할화면 절대 금지.

[장비 일관성]
- 모든 씬은 반드시 동일한 장비("{equipment_type}")만 묘사. 다른 장비 등장 금지.
"""


def build_system_prompt(equipment_type: str) -> str:
    forbidden = ", ".join(f'"{w}"' for w in _FORBIDDEN_WORDS)
    return _SYSTEM_BASE.format(forbidden=forbidden, equipment_type=equipment_type or "해당 SOP의 주요 장비")


THREE_MIN_TEMPLATE = """다음 SOP를 분석하여 3분 안전교육 영상 대본을 JSON으로 작성하세요.

SOP 내용:
{sop_json}

요구사항:
- 총 {scene_count}개 씬 (각 최대 10초)
- 5막 구조 필수 — 최소 씬 수: hook 1, conflict 3-4, consequence 4-5, resolution 7-8, rules 3-4
  (resolution 비중 최대화 — 올바른 작업 방법을 가장 상세히 보여줄 것)
- act는 반드시 다음 enum 중 하나: "hook" | "conflict" | "consequence" | "resolution" | "rules"
- 각 씬: scene_id, act, narration_ko, image_prompt, motion_prompt, camera, mood, on_screen_text

JSON 형식으로만 응답하세요 (배열):
[{{"scene_id": "S01", "act": "hook", "narration_ko": "...", "image_prompt": "...", "motion_prompt": "...", "camera": "...", "mood": "...", "on_screen_text": null}}]
"""

SHORTFORM_TEMPLATE = """다음 SOP를 분석하여 30초 shortform 안전교육 영상 대본을 JSON으로 작성하세요.

SOP 내용:
{sop_json}

요구사항:
- 정확히 5개 씬 (각 6초): S01=hook, S02=conflict, S03=consequence, S04=resolution, S05=rules
- 핵심 위험 1가지에 집중, resolution 씬에서 올바른 방법을 명확히 보여줄 것
- on_screen_text: conflict/consequence 씬에 위험 경고 문구, resolution/rules에 핵심 수칙 (한국어 10자 이내)
- act는 반드시 다음 enum 중 하나: "hook" | "conflict" | "consequence" | "resolution" | "rules"

JSON 형식으로만 응답하세요 (배열):
[{{"scene_id": "S01", "act": "hook", "narration_ko": "...", "image_prompt": "...", "motion_prompt": "...", "camera": "...", "mood": "...", "on_screen_text": null}}]
"""

REQUIRED_ACTS = {"hook", "conflict", "consequence", "resolution", "rules"}
