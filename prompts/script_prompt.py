SYSTEM_PROMPT = """당신은 산업 안전교육 영상 대본 전문가입니다.
SOP 문서를 분석하여 현장 근로자를 위한 안전교육 영상 대본을 작성합니다.
- 나레이션: 한국어로 작성, 짧고 명확하게 (씬당 1~3문장)
- 이미지 프롬프트: 영어로 작성, Stable Diffusion 스타일
- 3막 구조 준수: hook → conflict/consequence → resolution/rules
"""

THREE_MIN_TEMPLATE = """다음 SOP를 분석하여 3분 안전교육 영상 대본을 JSON으로 작성하세요.

SOP 내용:
{sop_json}

요구사항:
- 총 {scene_count}개 씬 (각 8초 이하)
- 3막 구조: hook 1개, conflict+consequence 여러 개, resolution+rules로 마무리
- 각 씬: scene_id, act, narration_ko, image_prompt, motion_prompt, camera, mood, on_screen_text

JSON 형식으로만 응답하세요 (배열):
[{{"scene_id": "S01", "act": "hook", "narration_ko": "...", "image_prompt": "...", "motion_prompt": "...", "camera": "...", "mood": "...", "on_screen_text": null}}]
"""

SHORTFORM_TEMPLATE = """다음 SOP를 분석하여 30초 안전교육 영상 대본을 JSON으로 작성하세요.

SOP 내용:
{sop_json}

요구사항:
- 총 4개 씬 (각 7~8초)
- 핵심 위험 1가지에 집중
- JSON 형식으로만 응답하세요 (배열)
"""
