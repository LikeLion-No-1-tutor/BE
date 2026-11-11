"""API 문서(Swagger)의 예시 값. 문서 모양 이름 → {필드: 예시}.

Swagger는 예시가 없으면 "string", 0으로 채웁니다. 실제로 볼 만한 값을 보이도록 여기에 모아 둡니다.
자료구조 수업 하나(자료 "자료구조: 스택과 큐", 학생 AI 민준, 용어 스택, 큐, 원형 큐)의 값으로 맞췄습니다.
새 DB에서 처음 만든 수업이라 가정하고,
Try it out에서 그대로 보내도 동작하도록 id는 1부터 씁니다.
common/test_api_docs.py가 모든 필드에 예시가 있는지, 예시가 필드 모양에 맞는지 확인합니다.
"""

ACCESS_TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwidXNlcl9pZCI6IjEifQ.c2lnbmF0dXJl'
REFRESH_TOKEN = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoicmVmcmVzaCIsInVzZXJfaWQiOiIxIn0.c2lnbmF0dXJl'
REQUEST_ID = '7f3c2a9e-1b4d-4c8e-9f21-5a6b7c8d9e0f'

STARTED_AT = '2026-11-11T14:00:00+09:00'
ENDED_AT = '2026-11-11T14:40:00+09:00'
CREATED_AT = '2026-11-11T14:42:10+09:00'

MATERIAL_TITLE = '자료구조: 스택과 큐'
EXPLANATION = '스택은 접시를 쌓는 것처럼 마지막에 넣은 데이터를 먼저 꺼내는 구조예요. 이걸 LIFO라고 해요.'

USER = {'id': 1, 'email': 'teacher@gmail.com', 'nickname': '선생님', 'onboarding_completed': True}
MESSAGE = {'id': 2, 'content': EXPLANATION, 'created_at': '2026-11-11T14:05:12+09:00'}
TERM = {'term_id': 1, 'name': '스택'}
RETEST_EXPLANATION = '스택은 LIFO 구조라 마지막에 넣은 데이터가 먼저 나와요.'
TOKENS = {'access_token': ACCESS_TOKEN, 'refresh_token': REFRESH_TOKEN}

COMPONENTS = {
    # 공통
    'ErrorBody': {'code': 'NOT_FOUND', 'message': '수업을 찾을 수 없어요.', 'request_id': REQUEST_ID},
    'StoredError': {'code': 'AI_ERROR', 'message': 'AI 처리에 실패했어요.', 'request_id': REQUEST_ID},

    # 로그인과 내 정보
    'GoogleLoginRequest': {'id_token': '구글 로그인으로 받은 ID 토큰'},
    'GoogleLoginResponse': {**TOKENS, 'is_new_user': False},
    'RefreshTokenRequest': {'refresh_token': REFRESH_TOKEN},
    'TokenPairResponse': TOKENS,
    'UserResponse': USER,
    'MeResponse': {**USER, 'created_at': '2026-11-01T20:15:00+09:00'},
    'PatchedMeUpdateRequest': {'nickname': '선생님', 'onboarding_completed': True},

    # 페르소나
    'Persona': {
        'id': 2, 'code': 'minjun', 'name': '민준', 'grade_label': '고1',
        'description': '교과서 수준은 알아요. 이유를 자주 물어요.',
    },
    'PersonaBrief': {'id': 2, 'name': '민준', 'grade_label': '고1'},

    # 자료
    'MaterialUploadRequest': {
        'title': MATERIAL_TITLE,
        'text': '스택은 LIFO 구조로 push와 pop으로 데이터를 넣고 뺀다. 큐는 FIFO 구조로 enqueue와 dequeue를 쓴다.',
    },
    'MaterialUploadResponse': {'id': 1, 'title': MATERIAL_TITLE},
    'MaterialStatusResponse': {'id': 1, 'title': MATERIAL_TITLE, 'file_name': '자료구조_스택과_큐.pdf', 'term_count': 3},
    'MaterialBrief': {'id': 1, 'title': MATERIAL_TITLE},

    # 수업
    'LessonStartRequest': {'material_id': 1, 'persona_id': 2},
    'LessonStartResponse': {'id': 1},
    'LessonDetailResponse': {
        'id': 1, 'raised_hand_count': 1, 'note_id': 1, 'report_id': 1,
        'started_at': STARTED_AT, 'ended_at': ENDED_AT,
    },
    'LessonTermItem': TERM,
    'TermSummary': {'explained': 2, 'total': 3},
    'GreetingMessage': {
        'id': 1, 'content': '선생님 안녕하세요! 오늘 자료구조: 스택과 큐 배우는 거죠? 잘 들을게요.',
        'created_at': STARTED_AT,
    },
    'MessageItem': {**MESSAGE, 'reply_to_id': None},
    'MessageSendRequest': {'content': EXPLANATION, 'reply_to_id': None},
    'HandRaiseItem': {'id': 1, 'after_message_id': 2, 'question_message_id': 3},
    'NewHandRaise': {'id': 1, 'after_message_id': 2},
    'MessageSentResponse': {'raised_hand_count': 1},
    'QuestionAskedResponse': {'raised_hand_count': 0},
    'LessonEndResponse': {'id': 1},
    'NoteStep': {'note_id': 1},
    'ExamStep': {'solved': 5, 'total': 5},
    'ReportStep': {'report_id': 1},
    'NoteResponse': {
        'id': 1, 'lesson_id': 1, 'persona_name': '민준',
        'content': (
            '# 자료구조: 스택과 큐 정리노트\n\n'
            '## 스택\n마지막에 넣은 데이터를 먼저 꺼내는 LIFO 구조. push로 넣고 pop으로 뺀다.\n\n'
            '## 큐\n먼저 넣은 데이터를 먼저 꺼내는 FIFO 구조. enqueue로 넣고 dequeue로 뺀다.'
        ),
        'created_at': CREATED_AT,
    },
    'LessonListItem': {
        'id': 1, 'title': MATERIAL_TITLE, 'persona_name': '민준', 'started_at': STARTED_AT,
        'score': 60, 'latest_score': 67, 'report_id': 1,
    },
    'LessonListResponse': {'page': 1, 'size': 20, 'total': 3},

    # 성장보고서
    'ReportListItem': {
        'id': 1, 'lesson_id': 1, 'title': MATERIAL_TITLE, 'score': 60, 'latest_score': 67, 'retest_count': 1,
        'created_at': CREATED_AT,
    },
    'ReportListResponse': {'page': 1, 'size': 20, 'total': 3},
    'ReportLesson': {
        'id': 1, 'title': MATERIAL_TITLE, 'persona_name': '민준', 'persona_grade_label': '고1',
        'started_at': STARTED_AT,
    },
    'ScoreHistoryItem': {'exam_id': 1, 'score': 60, 'completed_at': '2026-11-11T14:41:30+09:00'},
    'ScoreComparison': {'current_score': 67, 'previous_score': 60, 'diff': 7},
    'EvaluationSummary': {'correct': 3, 'total': 5},
    'EvaluationResult': {'number': 1, 'is_correct': True, 'term_id': 1},
    'TermCount': {'explained': 2, 'total': 3},
    'MissedTerm': {'term_id': 3, 'name': '원형 큐', 'wrong_count': 2},
    'ReviewRecommendation': {
        'term_id': 3, 'text': '원형 큐에서 front와 rear가 배열 끝에서 처음으로 돌아가는 과정을 그림으로 다시 설명해 보세요.',
    },
    'ReportDetailResponse': {
        'id': 1, 'score': 60,
        'strengths': ['스택을 접시 쌓기에 비유해 쉽게 설명했어요.', '학생 질문에 스택과 큐를 비교해 답했어요.'],
        'created_at': CREATED_AT, 'updated_at': '2026-11-12T09:10:00+09:00',
    },

    # 재시험
    'RetestStartResponse': {'id': 2},
    'RetestResponse': {'id': 2, 'report_id': 1, 'total': 3},
    'RetestQuestion': {
        'number': 1, 'content': '스택에서 pop을 하면 어떤 데이터가 나오나요?',
        'choices': ['가장 마지막에 넣은 데이터', '가장 먼저 넣은 데이터', '가장 작은 값'],
        'answered': True, 'response': '0', 'is_correct': True, 'correct_answer': '0',
        'explanation': RETEST_EXPLANATION,
    },
    'AnswerRequest': {'response': '0'},
    'AnswerResultResponse': {
        'number': 1, 'is_correct': True, 'correct_answer': '0',
        'explanation': RETEST_EXPLANATION,
    },
    'RetestCompleteResponse': {'id': 2, 'correct': 2, 'total': 3, 'score': 67, 'report_id': 1},
}

# 에러 코드마다 보여 줄 메시지
ERROR_MESSAGES = {
    'VALIDATION_ERROR': '요청 형식이 올바르지 않아요.',
    'UNSUPPORTED_FILE_TYPE': '지원하지 않는 파일 형식이에요.',
    'UNAUTHORIZED': '로그인이 필요해요.',
    'FORBIDDEN': '접근할 수 없는 데이터예요.',
    'NOT_FOUND': '찾을 수 없어요.',
    'NICKNAME_REQUIRED': '닉네임을 먼저 저장해 주세요.',
    'MATERIAL_NOT_READY': '자료 정리가 아직 끝나지 않았어요.',
    'MATERIAL_ALREADY_USED': '이미 수업에 쓴 자료예요.',
    'LESSON_NOT_TEACHING': '이미 종료된 수업이에요.',
    'HAND_ALREADY_ASKED': '이미 질문한 손 든 표시예요.',
    'NOTE_NOT_READY': '정리노트가 아직 준비되지 않았어요.',
    'RETEST_GENERATING': '재시험을 출제하는 중이에요.',
    'RETEST_NOT_SOLVING': '지금은 풀 수 없는 재시험이에요.',
    'QUESTION_ALREADY_ANSWERED': '이미 답한 문제예요.',
    'FILE_TOO_LARGE': '파일이 너무 커요.',
    'AI_ERROR': 'AI 처리에 실패했어요. 다시 시도해 주세요.',
}
