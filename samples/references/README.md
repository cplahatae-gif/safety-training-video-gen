# Reference Images

이 폴더에 레퍼런스 이미지를 넣으면 캐릭터 시트 생성과 씬 이미지 생성에 자동으로 반영됩니다.

## 파일명 규칙

| 파일명 | 용도 | 우선순위 |
|--------|------|---------|
| `person.jpg` / `person.png` | 인물 외모 (가장 중요) | 1순위 (character sheet ref) |
| `uniform.jpg` / `uniform.png` | 회사 유니폼 / PPE | 2순위 |
| `equipment.jpg` / `equipment.png` | 장비 레퍼런스 | 프롬프트 설명에만 사용 |

## 동작 방식 (Option C)

1. **캐릭터 시트 생성**: `person.jpg`를 FLUX-1.1-pro `image_prompt`로 사용
   - `image_prompt_strength=0.25` (씬 이미지보다 높게 설정해 외모 고정)
   - 5포즈(front/working/side/alert/instructive) 모두 레퍼런스 기반 생성

2. **씬 이미지 생성**: 캐릭터 시트 포즈(레퍼런스 기반) + 레퍼런스 텍스트 설명 주입
   - `image_prompt_strength=0.15`

## 레퍼런스 설명 자동 추출

`REFERENCE_DESCRIBE=1` 환경변수 설정 시 Gemini Vision이 이미지를 분석해
프롬프트에 주입할 설명을 자동 생성합니다 (호출 1회 추가).

## 주의사항

- 레퍼런스 없으면 기존 텍스트 기반 도메인 프롬프트로 자동 fallback
- Git 추적에서 제외 (`.gitignore`에 `samples/references/*.jpg` 추가 권장)
- 실제 인물 사진 사용 시 초상권 확인 필요
