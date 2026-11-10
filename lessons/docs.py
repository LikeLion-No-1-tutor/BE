"""수업 API의 문서 (Swagger). API 동작에는 쓰지 않습니다.

응답은 serializers.py의 *_data 함수가 dict로 만듭니다. 여기 모양을 바꾸면 그쪽도 같이 바꿉니다.
common/test_api_docs.py가 실제 응답과 이 모양이 같은지 확인합니다.
"""
from drf_spectacular.utils import OpenApiParameter
from rest_framework import serializers

from common.docs import MEMBER, OWNED, PAGE_PARAMETERS, StoredError, errors, operation, paged

from .models import HandRaise, Lesson, LessonTerm, Message
from .serializers import LessonStartRequest, MessagePageQuery, MessageSendRequest

TAG = '수업'
STEP_CHOICES = ['done', 'running', 'pending', 'failed']
EXAM_STEP_CHOICES = ['pending', 'generating', 'solving', 'grading', 'completed', 'failed']


class MaterialBrief(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()


class PersonaBrief(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    grade_label = serializers.CharField(help_text='예) 초5')


class LessonTermItem(serializers.Serializer):
    term_id = serializers.IntegerField()
    name = serializers.CharField()
    status = serializers.ChoiceField(
        choices=LessonTerm.Status.choices, help_text='todo: 아직, mentioned: 이름만 언급, explained: 설명함',
    )


class TermSummary(serializers.Serializer):
    explained = serializers.IntegerField(help_text='설명한 용어 수')
    total = serializers.IntegerField()


class GreetingMessage(serializers.Serializer):
    """reply_to_id가 없는 메시지 (첫 인사, 학생 질문)"""
    id = serializers.IntegerField()
    sender = serializers.ChoiceField(choices=Message.Sender.choices, help_text='teacher: 사용자, student: 학생 AI')
    kind = serializers.ChoiceField(choices=Message.Kind.choices)
    content = serializers.CharField()
    created_at = serializers.DateTimeField()


class MessageItem(GreetingMessage):
    reply_to_id = serializers.IntegerField(allow_null=True, help_text='답변이면 답한 학생 질문의 id')


class HandRaiseItem(serializers.Serializer):
    id = serializers.IntegerField()
    after_message_id = serializers.IntegerField(help_text='이 메시지 바로 아래에 손 든 표시를 그림')
    status = serializers.ChoiceField(choices=HandRaise.Status.choices, help_text='raised: 손 든 상태, asked: 질문함')
    question_message_id = serializers.IntegerField(allow_null=True, help_text='질문한 뒤의 학생 질문 메시지')


class NewHandRaise(serializers.Serializer):
    id = serializers.IntegerField()
    after_message_id = serializers.IntegerField()
    status = serializers.ChoiceField(choices=HandRaise.Status.choices)


class LessonStartResponse(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.ChoiceField(choices=Lesson.Status.choices)
    material = MaterialBrief()
    persona = PersonaBrief()
    terms = LessonTermItem(many=True)
    messages = GreetingMessage(many=True, help_text='학생 AI의 첫 인사 1개')


class LessonDetailResponse(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.ChoiceField(choices=Lesson.Status.choices)
    material = MaterialBrief()
    persona = PersonaBrief()
    terms = LessonTermItem(many=True)
    term_summary = TermSummary()
    raised_hand_count = serializers.IntegerField(help_text='아직 질문하지 않은 손 든 표시 수')
    note_id = serializers.IntegerField(allow_null=True)
    report_id = serializers.IntegerField(allow_null=True)
    started_at = serializers.DateTimeField()
    ended_at = serializers.DateTimeField(allow_null=True)


class LessonMessagesResponse(serializers.Serializer):
    messages = MessageItem(many=True, help_text='시간순')
    hand_raises = HandRaiseItem(many=True, help_text='돌려준 메시지 아래에 그릴 손 든 표시만')


class MessageSentResponse(serializers.Serializer):
    message = MessageItem()
    term_updates = LessonTermItem(many=True, help_text='이번 메시지로 상태가 바뀐 용어')
    term_summary = TermSummary()
    new_hand_raise = NewHandRaise(allow_null=True, help_text='학생 AI가 새로 손을 들었으면 값이 있음')
    raised_hand_count = serializers.IntegerField()


class QuestionAskedResponse(serializers.Serializer):
    hand_raise = HandRaiseItem()
    question = GreetingMessage(help_text='학생 AI의 질문')
    raised_hand_count = serializers.IntegerField()


class LessonEndResponse(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.ChoiceField(choices=Lesson.Status.choices, help_text='evaluating')


class NoteStep(serializers.Serializer):
    status = serializers.ChoiceField(choices=STEP_CHOICES)
    note_id = serializers.IntegerField(allow_null=True)


class ExamStep(serializers.Serializer):
    status = serializers.ChoiceField(choices=EXAM_STEP_CHOICES)
    solved = serializers.IntegerField(help_text='학생 AI가 푼 문제 수')
    total = serializers.IntegerField()


class ReportStep(serializers.Serializer):
    status = serializers.ChoiceField(choices=STEP_CHOICES)
    report_id = serializers.IntegerField(allow_null=True)


class LessonProgressResponse(serializers.Serializer):
    lesson_status = serializers.ChoiceField(choices=Lesson.Status.choices)
    note = NoteStep()
    exam = ExamStep()
    report = ReportStep()
    error = StoredError(allow_null=True, help_text='lesson_status가 failed일 때만 값이 있음')


class NoteResponse(serializers.Serializer):
    id = serializers.IntegerField()
    lesson_id = serializers.IntegerField()
    persona_name = serializers.CharField()
    content = serializers.CharField(help_text='마크다운')
    created_at = serializers.DateTimeField()


class LessonListItem(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField(help_text='자료 제목')
    persona_name = serializers.CharField()
    status = serializers.ChoiceField(choices=Lesson.Status.choices)
    started_at = serializers.DateTimeField()
    score = serializers.IntegerField(allow_null=True, help_text='학생 AI 평가 점수. 평가 전이면 null')
    latest_score = serializers.IntegerField(allow_null=True, help_text='재시험까지 포함한 가장 최근 점수')
    report_id = serializers.IntegerField(allow_null=True)


LessonListResponse = paged(LessonListItem, 'LessonListResponse')

ERRORS = errors(OWNED)

lesson_list = operation(
    'lesson_list', TAG, '학습 목록',
    description='최신순입니다.',
    parameters=[
        OpenApiParameter('status', str, enum=['teaching', 'completed'], description='빼면 전체'),
        *PAGE_PARAMETERS,
    ],
    responses={200: LessonListResponse, **errors(MEMBER, s400=['VALIDATION_ERROR'])},
)

lesson_start = operation(
    'lesson_start', TAG, '수업 시작',
    description='정리가 끝난(`ready`) 자료로 수업을 만듭니다. 자료 하나로 수업 하나만 만들 수 있습니다.',
    request=LessonStartRequest,
    responses={
        201: LessonStartResponse,
        **errors(OWNED, s400=['VALIDATION_ERROR'], s409=['MATERIAL_NOT_READY', 'MATERIAL_ALREADY_USED']),
    },
)

lesson_detail = operation(
    'lesson_detail', TAG, '수업 정보와 용어 체크리스트',
    responses={200: LessonDetailResponse, **ERRORS},
)

lesson_messages = operation(
    'lesson_messages', TAG, '수업 대화',
    description='`before`보다 앞선 메시지 중 최근 `limit`개를 시간순으로 줍니다. 처음에는 `before` 없이 부릅니다.',
    parameters=[
        OpenApiParameter('before', int, description='이 메시지 id보다 앞선 것만'),
        OpenApiParameter('limit', int, default=MessagePageQuery().fields['limit'].default, description='최대 200. 넘으면 200으로 줄임'),
    ],
    responses={200: LessonMessagesResponse, **errors(OWNED, s400=['VALIDATION_ERROR'])},
)

message_send = operation(
    'message_send', TAG, '설명과 답변 보내기',
    description=(
        '학생 AI가 설명을 듣고 용어 체크리스트를 갱신하고, 궁금한 점이 있으면 손을 듭니다. '
        '학생 질문에 답할 때는 `reply_to_id`에 질문 메시지 id를 넣습니다. AI를 기다리므로 몇 초 걸립니다.'
    ),
    request=MessageSendRequest,
    responses={
        201: MessageSentResponse,
        **errors(OWNED, s400=['VALIDATION_ERROR'], s409=['LESSON_NOT_TEACHING'], s502=['AI_ERROR']),
    },
)

hand_raise_ask = operation(
    'hand_raise_ask', TAG, '질문 받기',
    description='손 든 표시를 누르면 학생 AI가 질문합니다. AI를 기다리므로 몇 초 걸립니다.',
    responses={
        201: QuestionAskedResponse,
        **errors(OWNED, s409=['LESSON_NOT_TEACHING', 'HAND_ALREADY_ASKED'], s502=['AI_ERROR']),
    },
)

lesson_end = operation(
    'lesson_end', TAG, '수업 종료',
    description='정리노트, 학생 AI 평가, 성장보고서를 백그라운드에서 만듭니다. 진행 상태 API로 확인합니다.',
    responses={202: LessonEndResponse, **errors(OWNED, s409=['LESSON_NOT_TEACHING'])},
)

lesson_progress = operation(
    'lesson_progress', TAG, '수업 종료 뒤 진행 상태',
    description='정리노트, 평가, 성장보고서가 만들어지는 동안 1~2초마다 부릅니다.',
    responses={200: LessonProgressResponse, **ERRORS},
)

lesson_note = operation(
    'lesson_note', TAG, '정리노트',
    responses={200: NoteResponse, **errors(OWNED, s409=['NOTE_NOT_READY'])},
)
