# Safety Training Video Gen — 프로젝트 규칙

## 핵심 원칙: Stage 5 진입 전 사람 리뷰 필수

**Kling 영상 생성(Stage 5)은 씬당 ~$0.50이다. 시나리오나 이미지가 나쁜 채로 실행하면 돈 낭비다.**

자동 Gemini 점수(`--validate`)는 보조 수단이고, 최종 판단은 사람이 한다.
파이프라인은 Stage 3 완료 후와 Stage 4 완료 후에 자동으로 멈추고 확인을 요청한다.

---

## 단계별 확인 체크리스트

### Stage 3 완료 후 — 시나리오 확인

- [ ] 5막 전부 있는가: `hook` / `conflict` / `consequence` / `resolution` / `rules`
- [ ] `resolution` 씬이 "올바른 절차를 실행하는 장면"인가 (가장 비중 있어야 함)
- [ ] 나레이션(`narration_ko`)이 자연스러운 한국어인가
- [ ] 모든 씬에 동일한 장비명이 등장하는가 (`equipment_type` lock)
- [ ] 핵심 씬에 `on_screen_text`가 설정됐는가 (conflict/consequence/resolution/rules)
- [ ] `image_prompt`에 금지어가 없는가: split screen, composite, explosion, debris 등

**통과 → Stage 4 진행 / 실패 → `--stage 2-3` 재실행**

---

### Stage 4 완료 후 — 이미지 확인

출력된 폴더 경로에서 이미지를 직접 열어서 확인한다.

- [ ] 모든 씬에 동일한 장비가 있는가 (다른 장비 등장 금지)
- [ ] 분할화면·콜라주·사이드바이사이드가 없는가
- [ ] 작업자가 안전모·안전조끼 등 보호장비를 착용하고 있는가
- [ ] `consequence` 씬이 폭발 없이 정적 위험 표현인가 (기울어진 장비 + 경고 테이프)
- [ ] 캐릭터 복장이 씬 전체에서 일관되는가

**통과 → Stage 5 진행 / 실패 → `--stage 4 --run-id <id>` 재실행**

---

## 개발 명령

### 단계적 실행 (권장)

```powershell
$env:UV_PROJECT_ENVIRONMENT = "C:/Users/nomus/.venvs/safety-training-video-gen"

# Step 1: 시나리오 확인 (Stage 1-3, 사람 확인 게이트)
uv run python main.py --sop samples/고소작업차_아웃리거_점검.docx --duration 30

# Step 2: 이미지 생성 + 확인 (Stage 4, 사람 확인 게이트)
uv run python main.py --stage 4 --run-id <run_id>

# Step 3: 영상~최종 합본 (Stage 5-7)
uv run python main.py --stage 5-7 --run-id <run_id> --evaluate
```

### 자동화 실행 (CI / 비용 테스트용)

```powershell
$env:FORCE_RUN = "1"  # 사람 확인 게이트 전부 스킵
uv run python main.py --sop samples/고소작업차_아웃리거_점검.docx --duration 30
```

### 단계별 재실행

```powershell
# 시나리오 재생성
uv run python main.py --stage 2-3 --run-id <run_id>

# 특정 이미지만 재생성 (manifest에서 해당 씬 status를 audio_ready로 수동 변경 후)
uv run python main.py --stage 4 --run-id <run_id>

# 검증만 실행
uv run scripts/validate_stage.py --stage 3 --workspace workspace/<run_id>
uv run scripts/validate_stage.py --stage 4 --workspace workspace/<run_id>
```

### 테스트

```powershell
uv run pytest --tb=short -q
```

---

## 비용 참고

| 단계 | 모델 | 30초 영상 | 180초 영상 |
|------|------|----------|-----------|
| Stage 2 | Gemini | ~$0 | ~$0 |
| Stage 3 | Google TTS | ~$0 | ~$0 |
| Stage 4 | FLUX-1.1-pro | ~$0.20 | ~$0.88 |
| Stage 5 | Kling 2.5 | ~$0.50 | ~$9 |
| Stage 7 평가 | Gemini Vision | ~$0 | ~$0 |
| **합계** | | **~$0.70** | **~$10** |

> Stage 5 전 사람 확인으로 잘못된 이미지로 Kling을 돌리는 낭비를 방지한다.
