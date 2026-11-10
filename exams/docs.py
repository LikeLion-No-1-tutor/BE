"""성장보고서와 재시험 API의 문서 (Swagger). API 동작에는 쓰지 않습니다.

응답은 serializers.py의 *_data 함수가 dict로 만듭니다. 여기 모양을 바꾸면 그쪽도 같이 바꿉니다.
common/test_api_docs.py가 실제 응답과 이 모양이 같은지 확인합니다.
"""
from rest_framework import serializers

from common.docs import MEMBER, OWNED, PAGE_PARAMETERS, StoredError, errors, operation, paged
from lessons.models import LessonTerm

from .models import Exam, ExamQuestion
from .serializers import AnswerRequest, RetestStartRequest

REPORT = '성장보고서'
RETEST = '재시험'


class ReportListItem(serializers.Serializer):
    id = serializers.IntegerField()
    lesson_id = serializers.IntegerField()
    title = serializers.CharField(help_text='자료 제목')
    score = serializers.IntegerField(help_text='학생 AI 평가 점수')
    latest_score = serializers.IntegerField(allow_null=True, help_text='재시험까지 포함한 가장 최근 점수')
    retest_count = serializers.IntegerField(help_text='끝낸 재시험 수')
    created_at = serializers.DateTimeField()


ReportListResponse = paged(ReportListItem, 'ReportListResponse')


class ReportLesson(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    persona_name = serializers.CharField()
    persona_grade_label = serializers.CharField()
    started_at = serializers.DateTimeField()


class ScoreHistoryItem(serializers.Serializer):
    exam_id = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=Exam.Kind.choices, help_text='evaluation: 학생 AI 평가, retest: 재시험')
    score = serializers.IntegerField()
    completed_at = serializers.DateTimeField()


class ScoreComparison(serializers.Serializer):
    current_score = serializers.IntegerField()
    previous_score = serializers.IntegerField()
    diff = serializers.IntegerField()


class EvaluationResult(serializers.Serializer):
    number = serializers.IntegerField()
    is_correct = serializers.BooleanField(allow_null=True)
    term_id = serializers.IntegerField(allow_null=True)


class EvaluationSummary(serializers.Serializer):
    correct = serializers.IntegerField(allow_null=True)
    total = serializers.IntegerField(allow_null=True)
    results = EvaluationResult(many=True)


class TermCount(serializers.Serializer):
    explained = serializers.IntegerField()
    total = serializers.IntegerField()


class MissedTerm(serializers.Serializer):
    term_id = serializers.IntegerField()
    name = serializers.CharField()
    status = serializers.ChoiceField(choices=LessonTerm.Status.choices)
    wrong_count = serializers.IntegerField(help_text='이 용어로 낸 평가 문제 중 틀린 수')


class ReviewRecommendation(serializers.Serializer):
    term_id = serializers.IntegerField()
    text = serializers.CharField()


class ReportDetailResponse(serializers.Serializer):
    id = serializers.IntegerField()
    lesson = ReportLesson()
    score = serializers.IntegerField(help_text='학생 AI 평가 점수')
    score_history = ScoreHistoryItem(many=True, help_text='끝난 시험의 점수. 시간순')
    comparison = ScoreComparison(allow_null=True, help_text='가장 최근 점수와 바로 앞 점수. 시험이 2개 미만이면 null')
    exam = EvaluationSummary(help_text='학생 AI 평가 결과')
    terms = TermCount()
    strengths = serializers.ListField(child=serializers.CharField(), help_text='잘한 점')
    missed_terms = MissedTerm(many=True, help_text='설명하지 못한 용어')
    review_recommendations = ReviewRecommendation(many=True)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField(help_text='재시험 결과를 저장하면 바뀜')


class RetestStartResponse(serializers.Serializer):
    id = serializers.IntegerField(help_text='재시험 id')
    status = serializers.ChoiceField(choices=Exam.Status.choices, help_text='generating')


class RetestQuestion(serializers.Serializer):
    number = serializers.IntegerField()
    question_type = serializers.ChoiceField(choices=ExamQuestion.QuestionType.choices)
    content = serializers.CharField()
    choices = serializers.ListField(
        child=serializers.CharField(), allow_null=True, help_text='객관식 보기. 주관식이면 null',
    )
    answered = serializers.BooleanField()
    response = serializers.CharField(required=False, help_text='answered가 true일 때만')
    is_correct = serializers.BooleanField(required=False, help_text='answered가 true일 때만')
    correct_answer = serializers.CharField(required=False, help_text='answered가 true일 때만')
    explanation = serializers.CharField(required=False, help_text='answered가 true일 때만')


class RetestResponse(serializers.Serializer):
    id = serializers.IntegerField()
    report_id = serializers.IntegerField(allow_null=True)
    status = serializers.ChoiceField(
        choices=Exam.Status.choices, help_text='generating이면 1~2초 뒤에 다시 부름. solving이면 풀 수 있음',
    )
    total = serializers.IntegerField()
    error = StoredError(allow_null=True, help_text='status가 failed일 때만 값이 있음')
    questions = RetestQuestion(many=True, help_text='출제 중이면 빈 배열')


class AnswerResultResponse(serializers.Serializer):
    number = serializers.IntegerField()
    is_correct = serializers.BooleanField()
    correct_answer = serializers.CharField()
    explanation = serializers.CharField()


class RetestCompleteResponse(serializers.Serializer):
    id = serializers.IntegerField()
    status = serializers.ChoiceField(choices=Exam.Status.choices, help_text='completed')
    correct = serializers.IntegerField()
    total = serializers.IntegerField()
    score = serializers.IntegerField(help_text='0~100')
    report_id = serializers.IntegerField(allow_null=True)


ERRORS = errors(OWNED)

report_list = operation(
    'report_list', REPORT, '성장보고서 목록',
    description='최신순입니다.',
    parameters=PAGE_PARAMETERS,
    responses={200: ReportListResponse, **errors(MEMBER, s400=['VALIDATION_ERROR'])},
)

report_detail = operation(
    'report_detail', REPORT, '성장보고서 상세',
    responses={200: ReportDetailResponse, **ERRORS},
)

retest_start = operation(
    'retest_start', RETEST, '재시험 출제',
    description=(
        '문제는 백그라운드에서 만듭니다. 재시험 문제와 상태 API로 `solving`이 될 때까지 확인합니다. '
        '`focus`를 빼면 `missed_terms`입니다.'
    ),
    request=RetestStartRequest,
    responses={
        202: RetestStartResponse,
        **errors(OWNED, s400=['VALIDATION_ERROR'], s409=['RETEST_GENERATING']),
    },
)

retest_detail = operation(
    'retest_detail', RETEST, '재시험 문제와 상태',
    description='정답과 해설은 답을 낸 문제에만 들어 있습니다.',
    responses={200: RetestResponse, **ERRORS},
)

retest_answer = operation(
    'retest_answer', RETEST, '문제 풀이와 채점',
    description='객관식은 보기 번호(0부터)를 문자열로 보냅니다. 주관식은 AI가 채점하므로 몇 초 걸립니다.',
    request=AnswerRequest,
    responses={
        200: AnswerResultResponse,
        **errors(
            OWNED, s400=['VALIDATION_ERROR'], s409=['RETEST_NOT_SOLVING', 'QUESTION_ALREADY_ANSWERED'],
            s502=['AI_ERROR'],
        ),
    },
)

retest_complete = operation(
    'retest_complete', RETEST, '재시험 결과 저장',
    description='답하지 않은 문제는 오답으로 채점합니다.',
    responses={200: RetestCompleteResponse, **errors(OWNED, s409=['RETEST_NOT_SOLVING'])},
)
