# Agent 기반 리팩토링 (Phase A-C, 2026-05-02 야간 작업)

## TL;DR

- KAIST 레이저 PDF 첫 테스트에서 발견된 3대 문제 (시나리오 슬로건 / 캐릭터 모순 / 이미지 결함)를 research-backed agent 패턴으로 해결.
- 신규 코드: 5개 agent 모듈, 4개 prompt 파일, 38개 테스트 추가.
- 기존 동작 보존: `USE_LEGACY_SCRIPT=1`, `DISABLE_CHARACTER_SHEET=1`, `DISABLE_IMAGE_AGENT=1` 환경변수로 단계별 롤백 가능.
- **이 작업 중에는 FLUX/Kling을 한 번도 호출하지 않았음.** 비용 발생 0원. 코드 + mock 테스트만.

---

## Research 근거

가장 권위있는 자료는 **arxiv 2512.16954 "Lights, Camera, Consistency: A Multistage Pipeline for Character-Stable AI Video Stories"** (2025년 12월).

핵심 발견:
1. **Plan-then-generate** — 한 번에 결과 만드는 게 아니라 brief → structured plan → execute
2. **Identity Anchoring** — 단일 ref 이미지가 아니라 다각도 캐릭터 시트
3. **Vision self-critique** — 결과 보고 자가 개선
4. **Educational/safety content는 빠른 컷이 아니라 deliberate pacing**이 정답 (Visla pacing guide)

이걸 우리 파이프라인 갭과 매칭:

| 우리 갭 | 적용 패턴 |
|---------|-----------|
| 시나리오 슬로건 수준 | Plan-then-generate + Self-critique |
| 캐릭터 매번 다른 옷 | Identity Anchoring (다각도 시트) |
| 도메인 미스매치 (KAIST에 작업복) | Domain-aware character prefix |
| 목 없는 사람 등 결함 | Vision critique → 프롬프트 정제 → 재생성 |

---

## Phase A: ScenarioAgent

### 변경 파일

| 파일 | 종류 | 설명 |
|------|------|------|
| `pipeline/agents/__init__.py` | NEW | 패키지 마커 |
| `pipeline/agents/base_agent.py` | NEW | generate/critique/refine 공통 패턴 |
| `pipeline/agents/sop_extractor.py` | NEW | 도메인 판별 + deep_extract |
| `pipeline/agents/scenario_agent.py` | NEW | Brief → Rich JSON → Self-critique 루프 |
| `prompts/scenario_brief_prompt.py` | NEW | 한 단락 줄글 생성용 프롬프트 |
| `prompts/scenario_rich_prompt.py` | NEW | 5초 단위 씬 JSON 생성용 |
| `prompts/scenario_critique_prompt.py` | NEW | 자가평가 (5개 지표) |
| `models/scene_manifest.py` | EDIT | `SopJson.domain`, `SopJson.deep_extract` 필드 추가 |
| `pipeline/sop_parser.py` | EDIT | `enrich_sop()` 자동 호출 |
| `pipeline/script_gen.py` | EDIT | ScenarioAgent로 라우팅, legacy는 ENV로 fallback |
| `tests/test_scenario_agent.py` | NEW | 6개 테스트 |
| `tests/test_script_gen.py` | EDIT | autouse fixture로 legacy 강제 |
| `tests/test_sop_parser.py` | EDIT | autouse fixture로 enrich 비활성화 |

### 로직

```
1. enrich_sop(sop)
   ├─ detect_domain(sop) → "lab" | "industrial" | "medical" | "chemical" | "construction" | "general"
   └─ extract_deep_info(sop) → DeepExtract {
        specific_hazards, specific_procedures, equipment_details,
        injury_types, thresholds
      }

2. brief = generate_brief(sop, deep)
   → 5-7문장 줄글 (안전 메시지 + 시각 묘사 + 구체 수치)

3. scenes_v1 = generate_rich_json(brief, deep, scene_count, resolution_count)
   → 풍부한 씬 JSON (narration_ko 1-2문장 + image_prompt + motion_prompt + ...)

4. critique = self_critique(scenes_v1)
   ├─ 결정적 검사: 5막 + 금지어 (점수 차감, forbidden = 강제 fail)
   └─ Gemini text eval: specificity / act_coverage / equipment_lock / safety_accuracy / visual_clarity

5. if not critique.passed:
     scenes_v2 = refine(scenes_v1, critique.issues)
     critique = self_critique(scenes_v2)
     ... up to max_attempts (default 2)

6. return best scenes
```

### 결과물 형식

기존 `manifest.json` 형식 그대로 유지 (씬 리스트). `legacy generate_script()`와 100% 호환.

---

## Phase B: CharacterAgent

### 변경 파일

| 파일 | 종류 | 설명 |
|------|------|------|
| `prompts/character_prompts.py` | NEW | 도메인별 6종 캐릭터 프리픽스 + 5종 포즈 |
| `pipeline/agents/character_agent.py` | NEW | 시트 생성 + 씬별 포즈 선택 |
| `prompts/scene_prompt.py` | EDIT | `build_image_prompt(...)`에 `domain` 파라미터 추가 |
| `pipeline/scene_splitter.py` | EDIT | `split_scenes(...)`에 `domain` 파라미터 추가 |
| `pipeline/image_gen.py` | EDIT | CharacterAgent 호출 + 씬별 ref 선택 |
| `main.py` | EDIT | `sop["domain"]` 전달 |
| `pyproject.toml` | EDIT | `use_sheet` pytest 마커 등록 |
| `tests/test_character_agent.py` | NEW | 17개 테스트 |
| `tests/test_image_gen.py` | EDIT | sheet 비활성화 autouse fixture + 신규 sheet 테스트 |

### 도메인별 캐릭터 프리픽스

```python
CHARACTER_PROMPTS = {
  "industrial":   "navy blue uniform, reflective stripes, hard hat, safety gloves, steel-toe boots",
  "construction": "sturdy work clothes, yellow safety vest, hard hat, work gloves, heavy boots",
  "lab":          "clean white lab coat, laser safety goggles, nitrile gloves, closed-toe shoes",
  "medical":      "blue or green scrubs, name badge, latex gloves, surgical mask",
  "chemical":     "full chemical-resistant suit, respirator, chemical gloves, rubber boots",
  "general":      "neat work uniform, necessary PPE",
}
```

### 5포즈 시트

| 포즈 ID | 설명 | 매핑 액트 |
|---------|------|-----------|
| `front` | 정면, 중립 | hook |
| `working` | 작업 자세 | resolution |
| `side` | 측면 프로필 | (fallback) |
| `alert` | 경고/주의 | conflict, consequence |
| `instructive` | 지도하는 자세 | rules |

이 시트는 `workspace/<run>/character_sheet/` 폴더에 5장으로 저장됨.

### 로직

```
1. CharacterAgent.prepare(domain, workspace, equipment_hint)
   └─ 5장 PNG 생성 (FLUX-schnell, 캐시됨)

2. for each scene:
     pose_path = CharacterAgent.select(scene)  # act → 포즈 매핑
     scene_image = FLUX-1.1-pro(image_prompt, image_prompt=pose_path)
```

---

## Phase C: ImageAgent

### 변경 파일

| 파일 | 종류 | 설명 |
|------|------|------|
| `prompts/image_critique_prompt.py` | NEW | Vision 평가 + 프롬프트 정제 |
| `pipeline/agents/image_agent.py` | NEW | 생성/크리틱/리파인 루프 |
| `pipeline/image_gen.py` | EDIT | ImageAgent 통합 |
| `tests/test_image_agent.py` | NEW | 14개 테스트 |

### 5개 평가 지표

```json
{
  "anatomy": 0-10,         // 신체 정상성 (목 없는 사람, 떠있는 옷, 손가락 6개)
  "domain_match": 0-10,    // 도메인 일치 (lab에 작업복?)
  "no_split_screen": 0-10, // 단일 구도
  "equipment_match": 0-10, // 장비 정확성
  "composition": 0-10,     // 구도 품질
  "main_issue": "...",     // 가장 큰 문제 한 줄
  "retry_hint": "..."      // 재생성 시 키워드
}
```

평균 점수 < 7이면 재생성.

### 로직

```
attempt 1:
  ├─ FLUX-1.1-pro(prompt, ref=sheet_pose) — 시트 포즈로 character anchoring
  ├─ Gemini Vision critique → score
  └─ if score >= 7: return success

attempt 2 (if needed):
  ├─ refined_prompt = Gemini.refine(prompt, issues)
  ├─ FLUX-1.1-pro(refined_prompt, ref=sheet_pose)
  ├─ Gemini Vision critique
  └─ return best of 2 attempts
```

---

## 호환성 / 롤백

각 단계별로 환경변수로 끌 수 있음:

```bash
# Stage 2 — legacy one-shot Gemini로
USE_LEGACY_SCRIPT=1

# Stage 4a — 캐릭터 시트 안 만들고 첫 씬을 ref로 (이전 방식)
DISABLE_CHARACTER_SHEET=1

# Stage 4b — Vision critique 끄고 raw FLUX 출력
DISABLE_IMAGE_AGENT=1

# 셋 다 끄면 Phase A-C 이전 동작과 동일
USE_LEGACY_SCRIPT=1; DISABLE_CHARACTER_SHEET=1; DISABLE_IMAGE_AGENT=1
```

`FORCE_RUN=1` (사람 게이트 스킵)은 별도 변수 — agent 동작과 무관.

---

## 테스트 변화

```
Phase 시작 전: 52 passing
Phase A 후:    58 passing (+6)
Phase B 후:    76 passing (+18)
Phase C 후:    90 passing (+14)
```

**38개 신규 테스트 모두 mock 사용.** 외부 API 호출 0회. 비용 0원.

---

## 다음 단계 (사용자 결정 필요)

지금까지는 **코드만** 만들었다. 실제 Gemini/FLUX/Kling 호출은 0건. 비용 0원.

다음 검증을 위해 실제 호출이 필요:

1. **새 ScenarioAgent로 시나리오 재생성** — KAIST PDF 다시 돌려서 시나리오 깊이 비교
   - 비용: ~$0.01 (Gemini 무료 티어)
   - 위험: 낮음

2. **캐릭터 시트 1번 생성** — KAIST 도메인=lab으로 5장 생성
   - 비용: ~$0.02 (FLUX-schnell × 5)
   - 위험: 낮음

3. **이미지 1-2장 생성해서 ImageAgent 동작 확인**
   - 비용: ~$0.10 (FLUX-1.1-pro × 1-2 + Gemini Vision)
   - 위험: 낮음

총 검증 비용 ~$0.15 미만. 만족 시 Stage 5(영상 생성, $2-3)로 진행.

---

## 알려진 한계

1. **Kling 2.5 Turbo Pro 제약** — 5초 또는 10초만 지원. 더 짧은 컷은 ffmpeg 트림 필요.
2. **Nano Banana(Gemini Image)** 미통합 — 부분 편집(목 추가 등) 케이스에 활용 여지 있음. Phase D+로 미룸.
3. **Reference 이미지 검색** (SerpAPI/DuckDuckGo) 미구현 — Phase B의 캐릭터 시트로 대체. 필요 시 별도 phase.
4. **Domain 자동 판별 정확도** — Gemini가 SOP 보고 판별. 실제 KAIST PDF로 검증 안 됨.

---

## 커밋 이력

```
114a418 feat: Phase C — ImageAgent (Vision self-critique loop)
4681535 feat: Phase B — CharacterAgent (Identity Anchoring via reference sheet)
4264e39 feat: Phase A — ScenarioAgent (plan-then-generate, research-backed)
bd2e7b7 feat: human review gates before Stage 5 + CLAUDE.md
... (이전 커밋들)
```

push는 사용자 승인 받기 전에 안 함.
