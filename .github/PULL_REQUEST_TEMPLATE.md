<!--
제목 형식: 종류: 한 일   (예: feat: 구글 소셜 로그인 API 추가)
Squash 머지 시 PR 제목이 그대로 dev의 커밋 메시지가 됩니다. PR 번호는 제목에 적지 않습니다.
base는 dev, compare는 내 작업 브랜치인지 확인하고 Reviewers에 팀원 1명을 지정합니다.
(... 때만), (Optional) 표시가 있는 섹션은 해당할 때만 쓰고, 아니면 지웁니다.
-->

## Description
<!-- 무엇을 왜 바꿨는지 적습니다. -->
- 

## Type of Change
<!-- 해당 PR이 어떤 유형의 변경 사항을 포함하고 있는지 체크해주세요. -->
- [ ] Feature (새로운 기능 추가)
- [ ] Fix (버그 수정)
- [ ] Refactor (코드 리팩토링, 기능 변경 없음)
- [ ] Test (테스트 추가·수정)
- [ ] Docs (문서 수정)
- [ ] Chore (설정 변경, 패키지 추가 등)

## Details
<!-- 파일이나 기능별로 무엇을 어떻게 바꿨는지 적습니다. -->
- 

## How to Use API (API를 바꿨을 때만)
<!-- 요청 방법과 성공·실패 응답 예시를 적습니다. -->

## Test
### 자동 테스트
<!-- 직접 실행한 결과를 그대로 붙여넣습니다. -->
```text
$ uv run python manage.py check
(실행 결과를 붙여넣기)

$ uv run python manage.py makemigrations --check --dry-run
(실행 결과를 붙여넣기)

$ uv run python manage.py test
(실행 결과를 붙여넣기)
```

### 직접 확인
| 확인한 내용 | 기대 결과 | 실제 결과 |
|---|---|---|
|  |  |  |

## Related Issue
<!-- Resolves: #12 라고 쓰면 PR이 머지될 때 12번 이슈가 자동으로 닫힙니다. -->
- Resolves: #

## Note (Optional)
<!-- 리뷰어가 알아야 할 내용, 이번에 하지 않은 일, 남은 문제를 적습니다. -->
- 

## Checklist
<!-- 해결하지 못한 항목은 체크하지 말고 Note에 그대로 적습니다. -->
- [ ] base 브랜치가 `dev`다
- [ ] 위 테스트를 모두 통과했다
- [ ] 이번 작업의 테스트 코드를 추가했다 (추가하지 못했다면 이유를 Note에 적었다)
- [ ] `.env`, 비밀번호, API 키가 포함되지 않았다
- [ ] 모델을 바꿨다면 마이그레이션 파일을 포함했다
