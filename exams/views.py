from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from common import ai_client, jobs
from common.errors import ApiError
from common.pagination import PagePagination
from lessons.models import Lesson

from . import ai
from . import docs
from .models import Exam, ExamQuestion, Report
from .retest import run_retest_generate
from .serializers import (
    AnswerRequest,
    RetestStartRequest,
    answer_result_data,
    report_detail_data,
    report_list_item,
    retest_data,
)


def get_own_report(user, report_id):
    """내 성장보고서. 없으면 404, 다른 사용자의 보고서면 403."""
    report = (
        Report.objects.select_related('lesson__material', 'lesson__persona')
        .prefetch_related('lesson__exams')
        .filter(pk=report_id)
        .first()
    )
    if report is None:
        raise ApiError(404, 'NOT_FOUND', '성장보고서를 찾을 수 없어요.')
    if report.lesson.user_id != user.id:
        raise ApiError(403, 'FORBIDDEN', '접근할 수 없는 데이터예요.')
    return report


def get_own_retest(user, retest_id):
    """내 재시험. 없으면 404, 다른 사용자의 재시험이면 403. 평가 시험 ID는 재시험이 아니므로 404."""
    exam = Exam.objects.select_related('lesson').filter(pk=retest_id, kind=Exam.Kind.RETEST).first()
    if exam is None:
        raise ApiError(404, 'NOT_FOUND', '재시험을 찾을 수 없어요.')
    if exam.lesson.user_id != user.id:
        raise ApiError(403, 'FORBIDDEN', '접근할 수 없는 데이터예요.')
    return exam


def ensure_solving(exam):
    if exam.status != Exam.Status.SOLVING:
        raise ApiError(409, 'RETEST_NOT_SOLVING', '지금은 풀 수 없는 재시험이에요.')


def _report_id(lesson_id):
    return Report.objects.filter(lesson_id=lesson_id).values_list('id', flat=True).first()


class ReportListView(APIView):
    """GET /api/reports: 성장보고서 목록 (최신순)"""

    @docs.report_list
    def get(self, request):
        reports = (
            Report.objects.filter(lesson__user=request.user)
            .select_related('lesson__material')
            .prefetch_related('lesson__exams')
            .order_by('-created_at', '-id')
        )
        paginator = PagePagination()
        page = paginator.paginate_queryset(reports, request, view=self)
        return paginator.get_paginated_response([report_list_item(report) for report in page])


class ReportDetailView(APIView):
    """GET /api/reports/{report_id}: 성장보고서 상세"""

    @docs.report_detail
    def get(self, request, report_id):
        return Response(report_detail_data(get_own_report(request.user, report_id)))


class RetestStartView(APIView):
    """POST /api/reports/{report_id}/retests: 재시험 출제

    재시험을 generating으로 만들고, 커밋한 뒤 백그라운드 작업 retest_generate를 등록한다.
    """

    @docs.retest_start
    def post(self, request, report_id):
        report = get_own_report(request.user, report_id)
        body = RetestStartRequest(data=request.data)
        if not body.is_valid():
            raise ApiError(400, 'VALIDATION_ERROR', 'focus는 missed_terms 또는 all이어야 해요.')
        focus = body.validated_data['focus']

        with transaction.atomic():
            # 출제 버튼을 두 번 눌러도 하나만 생기게 수업을 잠그고 확인
            Lesson.objects.select_for_update().get(pk=report.lesson_id)
            generating = Exam.objects.filter(
                lesson_id=report.lesson_id, kind=Exam.Kind.RETEST, status=Exam.Status.GENERATING,
            )
            if generating.exists():
                raise ApiError(409, 'RETEST_GENERATING', '재시험을 출제하는 중이에요.')
            exam = Exam.objects.create(
                lesson_id=report.lesson_id, kind=Exam.Kind.RETEST, status=Exam.Status.GENERATING,
                question_count=settings.EXAM_QUESTION_COUNT,
            )
            jobs.enqueue(run_retest_generate, exam.id, focus, request.request_id)

        return Response({'id': exam.id, 'status': exam.status}, status=status.HTTP_202_ACCEPTED)


class RetestDetailView(APIView):
    """GET /api/retests/{retest_id}: 재시험 문제·상태"""

    @docs.retest_detail
    def get(self, request, retest_id):
        exam = get_own_retest(request.user, retest_id)
        return Response(retest_data(exam, _report_id(exam.lesson_id)))


class RetestAnswerView(APIView):
    """POST /api/retests/{retest_id}/questions/{number}/answer: 문제 풀이 및 채점

    객관식은 보기 번호를 그대로 비교하고, 주관식은 주관식 채점 AI를 실시간으로 부른다 (실패하면 저장하지 않음).
    """

    @docs.retest_answer
    def post(self, request, retest_id, number):
        exam = get_own_retest(request.user, retest_id)
        ensure_solving(exam)
        question = exam.questions.filter(number=number).first()
        if question is None:
            raise ApiError(404, 'NOT_FOUND', '없는 문제 번호예요.')
        if question.response is not None:
            raise ApiError(409, 'QUESTION_ALREADY_ANSWERED', '이미 답한 문제예요.')
        response = self._valid_response(question, request.data)

        if question.question_type == ExamQuestion.QuestionType.MULTIPLE_CHOICE:
            is_correct = ai.is_choice_correct(question, response)
        else:
            is_correct = self._grade_short_answer(request, question, response)

        with transaction.atomic():
            exam = Exam.objects.select_for_update().get(pk=exam.pk)
            ensure_solving(exam)  # AI를 기다리는 사이 결과를 저장했을 수 있음
            question = ExamQuestion.objects.select_for_update().get(pk=question.pk)
            if question.response is not None:  # 같은 문제를 거의 동시에 두 번 냄
                raise ApiError(409, 'QUESTION_ALREADY_ANSWERED', '이미 답한 문제예요.')
            question.response = response
            question.is_correct = is_correct
            question.answered_at = timezone.now()
            question.save(update_fields=['response', 'is_correct', 'answered_at'])

        return Response(answer_result_data(question))

    @staticmethod
    def _valid_response(question, data):
        body = AnswerRequest(data=data)
        if not body.is_valid():
            raise ApiError(400, 'VALIDATION_ERROR', '답은 1~3,000자로 입력해 주세요.')
        response = body.validated_data['response']
        if question.question_type == ExamQuestion.QuestionType.MULTIPLE_CHOICE:
            if response not in {str(i) for i in range(len(question.choices or []))}:
                raise ApiError(400, 'VALIDATION_ERROR', '객관식 답은 보기 번호여야 해요.')
        return response

    @staticmethod
    def _grade_short_answer(request, question, response):
        numbers = {question.number}
        payload = ai.grade_payload([question], responses={question.number: response})
        try:
            grades = ai_client.call(
                ai.GRADE_PATH, json=payload, request_id=request.request_id,
                user_id=request.user.id, mode=ai_client.REALTIME,
                parse=lambda body: ai.parse_grades(body, numbers),
            )
        except ai_client.AiError as error:
            raise error.to_api_error()
        return grades[question.number]


class RetestCompleteView(APIView):
    """POST /api/retests/{retest_id}/complete: 재시험 결과 저장

    답하지 않은 문제는 오답으로 채점하고 점수를 저장한다. 보고서의 updated_at을 갱신한다.
    """

    @docs.retest_complete
    def post(self, request, retest_id):
        exam = get_own_retest(request.user, retest_id)
        ensure_solving(exam)
        with transaction.atomic():
            exam = Exam.objects.select_for_update().get(pk=exam.pk)
            ensure_solving(exam)  # 결과 저장을 두 번 눌러도 한 번만 반영
            exam.questions.filter(response=None).update(is_correct=False)
            correct = exam.questions.filter(is_correct=True).count()
            exam.correct_count = correct
            exam.score = round(correct * 100 / exam.question_count)
            exam.status = Exam.Status.COMPLETED
            exam.completed_at = timezone.now()
            exam.save(update_fields=['correct_count', 'score', 'status', 'completed_at'])
            report = Report.objects.filter(lesson_id=exam.lesson_id).first()
            if report is not None:
                report.save(update_fields=['updated_at'])  # auto_now로 지금 시각

        return Response({
            'id': exam.id,
            'status': exam.status,
            'correct': exam.correct_count,
            'total': exam.question_count,
            'score': exam.score,
            'report_id': report.id if report is not None else None,
        })
