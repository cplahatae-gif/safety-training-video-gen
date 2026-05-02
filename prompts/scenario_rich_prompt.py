"""Scene cutter prompt — turns an approved treatment into structured scene cards.

Takes the long-form treatment as input and decomposes it into per-scene JSON
with image_prompt / motion_prompt / bgm_keywords / on_screen_text. Narration
is intentionally left blank for now (future: TTS layer).
"""

RICH_SCENES_PROMPT = """\
당신은 안전 캠페인 영상의 편집/감독입니다.
아래 승인된 트리트먼트를 5초 단위 씬으로 컷팅하여 풍부한 JSON으로 출력합니다.
나레이션은 사용하지 않습니다 — 비주얼·자막·BGM으로 메시지를 전달.

[트리트먼트 (소스)]
{treatment}

[SOP 참고 정보]
- 제목: {sop_title}
- 도메인: {domain}
- 장비: {equipment_type}
- 위험: {specific_hazards}
- 절차: {specific_procedures}
- 부상: {injury_types}
- 기준: {thresholds}

---

요구사항:
- **정확히 {scene_count}개 씬**, 각 씬 5-10초
- 5막 분포 강제:
  - hook: 1씬
  - conflict: 1-2씬
  - consequence: 1씬
  - resolution: {resolution_count}씬 (가장 많이)
  - rules: 1씬
- 각 씬은 트리트먼트의 해당 섹션을 시각적으로 충실히 반영해야 함

각 씬 필드 (모두 필수):
- `scene_id`: "S01", "S02", ... 순서
- `act`: "hook" | "conflict" | "consequence" | "resolution" | "rules"
- `duration_sec`: 정수, 5-10 사이 (Kling 5초/10초 표준)
- `narration_ko`: **빈 문자열 ""** (이번 영상은 나레이션 없음)
- `image_prompt`: **영문**, FLUX용 단일 프레임 시각 묘사
  - 단일 연속 샷 (single continuous shot)
  - 도메인에 맞는 환경 (lab→optical table with laser equipment, industrial→worksite 등)
  - 구체적 장면 묘사 (조명, 자세, 장비 위치, 카메라 각도)
  - 트리트먼트의 해당 장면 묘사를 영문으로 충실히 옮김
  - **금지**: split screen, composite, montage, side by side, before/after, explosion, debris, glass shards, chaos
- `motion_prompt`: **영문**, Kling용 카메라/모션
  - 단일 카메라 움직임 (slow zoom in, tracking shot left, static + ambient hand motion)
  - 자연스러운 모션 (작업자가 실제 할 만한 동작)
- `camera`: 카메라 표기 (예: "low angle close-up", "wide shot static")
- `mood`: 분위기 (예: "tense", "instructive", "warning", "resolute")
- `on_screen_text`: 화면 자막 (한국어, 10자 이내, 핵심 메시지 — 트리트먼트의 자막 후보 사용)
  - hook: null 또는 짧은 setup
  - conflict: 위반 행동 명시 (예: "예열 미실시")
  - consequence: 결과/부상 (예: "망막 손상")
  - resolution: 핵심 수치/절차 (예: "약 2시간 예열", "최저 출력")
  - rules: 행동 강령 (예: "수칙 준수! 0119")
- `bgm_keywords`: 영문 검색 키워드 **2-3개 배열** (royalty-free 라이브러리 검색용)
  - 예: ["tense low drone", "ticking clock", "industrial ambient"]
  - 트리트먼트의 BGM 키워드 섹션을 활용

JSON 배열로만 출력 (다른 텍스트/마크다운 없이):
[
  {{"scene_id": "S01", "act": "hook", "duration_sec": 5, "narration_ko": "", "image_prompt": "...", "motion_prompt": "...", "camera": "...", "mood": "...", "on_screen_text": null, "bgm_keywords": ["...", "..."]}},
  ...
]
"""
