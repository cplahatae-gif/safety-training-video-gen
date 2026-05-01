# 추후 처리할 일 (Followups)

> 지금 당장은 아니고, 정리되는 대로 해야 할 목록. 날짜/담당 기록 추가하면서 관리.

---

## 🔴 긴급 — 키 로테이션 (Drive 동기화 노출)

**배경:** `.env`가 `E:\...\구글 동기화\...` 폴더 안에 평문으로 있었음. Drive 서버 및 연동된 모든 디바이스로 복제되었을 가능성. 이미 Drive 밖으로 이동(2026-04-19 완료)했지만, **과거에 올라갔던 사본은 되돌릴 수 없음**. 따라서 해당 키들은 "유출되었다고 가정" — 무효화 필요.

### [ ] Replicate API 토큰 로테이션
- **이유:** 유출 시 이미지/영상 생성으로 **실제 과금 발생** ($0.05/초 등). 우선순위 높음.
- **기존 토큰:** `[REDACTED — ~/.secrets/safety-video-gen/.env 참조]` (유출 가정)
- **절차:**
  1. https://replicate.com/account/api-tokens 접속
  2. 기존 토큰 **Revoke**
  3. **Create token** → 새 토큰 복사
  4. `C:/Users/nomus/.secrets/safety-video-gen/.env`의 `REPLICATE_API_TOKEN` 값 교체
  5. `uv run python -c "import replicate; print(replicate.models.get('black-forest-labs/flux-schnell'))"` 로 로드 테스트

### [ ] Gemini API 키 로테이션
- **이유:** 무료 티어라 과금 위험 낮음. 하지만 quota 남용 가능 + 어차피 교체 비용 0에 가까움.
- **기존 키:** `[REDACTED — ~/.secrets/safety-video-gen/.env 참조]` (유출 가정)
- **절차:**
  1. https://aistudio.google.com/apikey 접속
  2. 기존 키 옆 **Delete**
  3. **Create API key** → 새 키 복사
  4. `.env`의 `GEMINI_API_KEY` 값 교체
  5. `uv run python -c "import google.genai; ..."` 로 로드 테스트

### [x] Google Cloud TTS 서비스 계정 키 로테이션 (2026-04-19 완료)
- 기존 키 ID: `937dc6a1eba86919770d34ddc02122f21df71522` → GCP에서 삭제
- 새 키: `1b082d2833bf1a5a09683f82f7af6270c520c9d3` (`.secrets/safety-video-gen/tts-key.json`)

---

## 🟡 코드 리뷰 Important 항목 (Gate 3 patch 이월분)

Critical + High는 전부 반영 완료(커밋 `d33ce84`). 아래는 중요도 낮지만 production 전 처리 권장.

### [ ] FFmpeg subprocess 에러 래핑
- **위치:** `pipeline/assembler.py`의 `subprocess.run(..., check=True, capture_output=True)` 3곳
- **문제:** FFmpeg 실패 시 `CalledProcessError`만 raise됨. stderr가 로그에 안 찍혀서 디버깅 어려움.
- **수정:** `try/except CalledProcessError` 로 감싸서 `exc.stderr.decode()` 를 콘솔에 출력 후 re-raise.

### [ ] Image/Video 다운로드 빈 바이트 가드
- **위치:** `pipeline/image_gen.py:57`, `pipeline/video_gen.py` 비슷한 부분
- **문제:** `output[0].read()` 가 빈 bytes를 반환하면 0바이트 png/mp4 파일이 생성됨. 다음 단계에서 FFmpeg/assembler가 애매한 에러로 실패.
- **수정:** `if not data: raise ValueError("empty response from <model>")` 한 줄 추가.

### [ ] Assembler `merged_ready` 체크포인트 무결성 검증
- **위치:** `pipeline/assembler.py`의 `if merged_path.exists(): continue` 부분
- **문제:** 이전 실행이 중간에 죽어서 `<scene>_merged.mp4` 가 0바이트 또는 손상된 상태로 남아있으면, 스킵되어 concat 단계에서 실패.
- **수정:** 최소 파일 크기 체크 (e.g., `stat().st_size < 1024`) 또는 `ffprobe` 로 duration 있는지 확인.

### [ ] `google.generativeai` → `google.genai` 마이그레이션
- **위치:** `pipeline/script_gen.py` (Gemini 호출 부분)
- **문제:** `google.generativeai` 패키지는 **2025-11 공식 deprecation**. 신규 SDK는 `google-genai`.
- **수정:** `pip install google-genai` → import 및 API 호출 문법 전환. 공식 마이그레이션 가이드 참고.

---

## 🟢 운영 / 검증

### [ ] Replicate 월 예산 알림 설정
- https://replicate.com/account/billing → **Spending limits** 에 월 한도 ($50 권장) + 80% 알림 메일.
- **이유:** 루프 버그로 수십 번 재시도 나갈 경우 빠르게 인지.

### [ ] 첫 end-to-end 테스트 실행 (30초 shortform)
- 30초 영상 1개 생성으로 전체 파이프라인 smoke test.
- 비용 추정: $0.5~1 (이미지 6~8장 + 30초 Kling + TTS).
- 명령:
  ```bash
  cd "E:/.shortcut-targets-by-id/1A0SIVshe4TvCKXlR-jr-FdeHp3oYIIPJ/구글 동기화/claude/safety-training-video-gen"
  uv run python main.py --sop path/to/test-sop.docx --duration 30
  ```
- 성공 시 → 180초 production 실행.

### [ ] `/ultrareview` 실행
- 구현이 안정화된 후 Pro/Max 무료 쿼터 1회 사용.
- 현 시점 기준 critical/high 0건인지 독립 검증.

---

## 📦 Phase 2 (PoC 성공 이후)

- [ ] 다국어 나레이션 (ko/en/zh/vi 등 — 외국인 근로자 대응)
- [ ] 웹 UI (SOP 업로드 → 영상 다운로드, SHE 현업이 직접 사용)
- [ ] 콘텐츠 검수 워크플로 (법무/안전팀 검토 후 승인 → 배포)
- [ ] 배치 처리 (여러 SOP 한번에 생성)
