"""Rich JSON scene generation prompt — informed by story brief + deep SOP extract.

Outputs structured scene list with per-scene narration, image_prompt, motion_prompt.
Each scene has 5-second target duration (matches Kling 5s standard).
"""

RICH_SCENES_PROMPT = """\
당신은 안전교육 영상 감독입니다. 아래 스토리 brief를 5초 단위 씬으로 컷팅하여 풍부한 JSON으로 출력합니다.

[스토리 Brief]
{brief}

[SOP 핵심 정보]
- 제목: {sop_title}
- 도메인: {domain}
- 장비: {equipment_type}

[참고할 구체 정보]
- 위험: {specific_hazards}
- 절차: {specific_procedures}
- 부상: {injury_types}
- 기준: {thresholds}

---

요구사항:
- **정확히 {scene_count}개 씬**, 각 씬 5초
- 5막 분포 강제:
  - hook: 1씬
  - conflict: 1-2씬
  - consequence: 1씬
  - resolution: {resolution_count}씬 (가장 많이)
  - rules: 1씬

각 씬 필드:
- `scene_id`: "S01", "S02", ... 순서
- `act`: "hook" | "conflict" | "consequence" | "resolution" | "rules"
- `narration_ko`: **1-2문장**, 구체 정보 1개 이상 인용 (수치, 절차, 부상 중 하나)
  - 슬로건 금지
  - "강력한 X" 같은 일반 묘사 금지
  - "0.5초 노출로 망막 영구손상" 같은 구체적 표현
- `image_prompt`: **영문**, FLUX용 시각 묘사
  - 단일 연속 샷 (single continuous shot)
  - 도메인에 맞는 환경 (lab→optical table, industrial→worksite 등)
  - 구체적 장면 묘사 (조명, 자세, 장비 위치)
  - **금지**: split screen, composite, montage, side by side, before/after, explosion, debris, glass shards, chaos
- `motion_prompt`: **영문**, Kling용 모션
  - 단일 카메라 움직임 (slow zoom, tracking shot, static + ambient)
  - 자연스러운 모션 (작업자가 실제 할 만한 동작)
- `camera`: 카메라 표기 (예: "low angle close-up", "wide shot static")
- `mood`: 분위기 (예: "tense", "instructive", "warning")
- `on_screen_text`: 화면 자막
  - hook: null 가능
  - conflict/consequence: 위험 경고 (10자 이내, 예: "위험!", "사고 발생!")
  - resolution: 핵심 동작 (예: "올바른 절차!", "보호 장비 착용!")
  - rules: 핵심 수칙 (예: "수칙 준수!")

JSON 배열로만 출력 (다른 텍스트 없이):
[
  {{"scene_id": "S01", "act": "hook", "narration_ko": "...", "image_prompt": "...", "motion_prompt": "...", "camera": "...", "mood": "...", "on_screen_text": null}},
  ...
]
"""
