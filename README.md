# 티칭로그

1호선톤, 팀 '1타강사'의 AI를 통한 학습 서비스
사용자가 선생님이 되어 AI 학생을 가르치며 공부하는 서비스입니다.

## 빠른 시작

### 사전 요구사항

- MySQL 8.4 LTS 버전
- Python 3.14.3(를 저는 썼어요)

### 설치 방법

#### 1. 원격 레포지토리 클론
`git clone https://github.com/LikeLion-No-1-tutor/BE.git`

`cd BE`

#### 2. 환경 변수 설정
`python -m venv venv`

`source venv/Scripts/activate   #Mac: source/bin/activate`

`pip install -r requirements.txt`

#### 3. 환경 변수 설정
루트 폴더에 .env 파일을 생성하고 노션에 있는 코드 붙여넣기

#### 4. 데이터베이스 마이그레이션 후 서버 켜기
`python manage.py migrate`

`python manage.py runserver`
