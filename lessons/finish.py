"""수업 종료의 백그라운드 처리 (lesson_finish). common.jobs.enqueue로 등록한다.

정리노트 → 평가 출제 → 학생 AI 풀이 → 주관식 채점 → 성장보고서 → completed

- AI를 기다리는 동안에는 트랜잭션을 열지 않고, 결과를 저장할 때만 연다.
- AI 호출은 ai_client의 BACKGROUND 모드라 실패하면 한 번 다시 부른다 (응답 모양이 틀린 것도 포함).
  또 실패하면 lessons.status = failed, lessons.error. 평가 단계에서 실패했으면 exams에도 같은 내용.
- 이미 끝난 단계는 건너뛴다 (정리노트·보고서가 있으면, 평가가 completed면). 같은 수업으로 다시 돌려도 안전하게.
"""
import logging
import time

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from common import ai_client
from exams import ai as exam_ai
from exams.models import Exam, ExamQuestion, Report

from . import ai
from .models import Lesson, Note

logger = logging.getLogger(__name__)

JOB = 'lesson_finish'
EXAM_STEPS = {'exam_generate', 'exam_solve', 'exam_grade'}


def run_lesson_finish(lesson_id, request_id):
    lesson = Lesson.objects.select_related('material', 'persona').filter(pk=lesson_id).first()
    if lesson is None or lesson.status != Lesson.Status.EVALUATING:
        # 탈퇴로 지워졌거나 이미 처리가 끝난 수업
        logger.warning('lesson_finish skipped', extra={
            'event': 'job_skipped', 'job': JOB, 'target_id': lesson_id, 'request_id': request_id,
        })
        return

    started = time.monotonic()
    log_fields = {'job': JOB, 'target_id': lesson.id, 'request_id': request_id}
    logger.info('job started', extra={'event': 'job_started', **log_fields})
    runner = _Runner(lesson, request_id)
    try:
        runner.run()
    except ai_client.AiError as error:
        runner.fail(error.as_error_json(request_id))
        logger.error('job failed', extra={
            'event': 'job_failed', **log_fields, 'duration_ms': _ms(started),
            'step': runner.step, 'error_code': error.original_code,
        })
        return
    except Exception:
        runner.fail(ai_client.AiError('AI_ERROR', '예상하지 못한 오류', 'UNEXPECTED').as_error_json(request_id))
        logger.exception('job failed', extra={
            'event': 'job_failed', **log_fields, 'duration_ms': _ms(started),
            'step': runner.step, 'error_code': 'UNEXPECTED',
        })
        raise
    logger.info('job finished', extra={'event': 'job_finished', **log_fields, 'duration_ms': _ms(started)})


class _Runner:
    def __init__(self, lesson, request_id):
        self.lesson = lesson
        self.request_id = request_id
        self.exam = None
        self.step = None

    def run(self):
        self.step = 'note'
        self._write_note()
        self.exam = self._evaluation_exam()
        if self.exam.status != Exam.Status.COMPLETED:
            self.step = 'exam_generate'
            self._generate()
            self.step = 'exam_solve'
            self._solve()
            self.step = 'exam_grade'
            self._grade()
            self._score()
        self.step = 'report'
        self._write_report()
        Lesson.objects.filter(pk=self.lesson.pk, status=Lesson.Status.EVALUATING).update(
            status=Lesson.Status.COMPLETED,
        )

    def fail(self, error_json):
        with transaction.atomic():
            Lesson.objects.filter(pk=self.lesson.pk).update(status=Lesson.Status.FAILED, error=error_json)
            if self.exam is not None and self.step in EXAM_STEPS:
                Exam.objects.filter(pk=self.exam.pk).update(status=Exam.Status.FAILED, error=error_json)

    def _ai(self, path, payload, parse):
        return ai_client.call(
            path, json=payload, request_id=self.request_id, mode=ai_client.BACKGROUND,
            user_id=self.lesson.user_id, parse=parse,
        )

    # 1. 정리노트
    def _write_note(self):
        if Note.objects.filter(lesson=self.lesson).exists():
            return
        content = self._ai(ai.NOTE_PATH, ai.note_payload(self.lesson), ai.parse_note)
        Note.objects.create(lesson=self.lesson, content=content)

    # 2. 평가 출제
    def _evaluation_exam(self):
        exam = self.lesson.exams.filter(kind=Exam.Kind.EVALUATION).first()
        if exam is not None and exam.status == Exam.Status.COMPLETED:
            return exam
        if exam is not None:  # 지난번에 중간에서 멈춘 평가는 처음부터 다시
            exam.delete()
        return Exam.objects.create(
            lesson=self.lesson, kind=Exam.Kind.EVALUATION, status=Exam.Status.GENERATING,
            question_count=settings.EVALUATION_QUESTION_COUNT,
        )

    def _generate(self):
        material = self.lesson.material
        term_ids = set(material.terms.values_list('id', flat=True))
        payload = exam_ai.generate_payload(
            material, Exam.Kind.EVALUATION, settings.EVALUATION_QUESTION_COUNT, settings.EXAM_QUESTION_TYPES,
        )
        questions = self._ai(exam_ai.GENERATE_PATH, payload, lambda body: exam_ai.parse_generated(body, term_ids))
        with transaction.atomic():
            ExamQuestion.objects.bulk_create(ExamQuestion(exam=self.exam, **q) for q in questions)
            self.exam.question_count = len(questions)
            self.exam.status = Exam.Status.SOLVING
            self.exam.save(update_fields=['question_count', 'status'])

    # 3. 학생 AI 풀이. 객관식은 바로 채점
    def _solve(self):
        questions = list(self.exam.questions.all())
        numbers = {q.number for q in questions}
        payload = exam_ai.solve_payload(self.lesson, questions)
        answers = self._ai(exam_ai.SOLVE_PATH, payload, lambda body: exam_ai.parse_answers(body, numbers))
        now = timezone.now()
        for question in questions:
            question.response = answers[question.number]
            question.answered_at = now
            if question.question_type == ExamQuestion.QuestionType.MULTIPLE_CHOICE:
                question.is_correct = exam_ai.is_choice_correct(question, question.response)
        has_short_answer = any(q.question_type == ExamQuestion.QuestionType.SHORT_ANSWER for q in questions)
        with transaction.atomic():
            ExamQuestion.objects.bulk_update(questions, ['response', 'answered_at', 'is_correct'])
            if has_short_answer:
                self.exam.status = Exam.Status.GRADING
                self.exam.save(update_fields=['status'])

    # 4. 주관식 채점
    def _grade(self):
        short_answers = list(self.exam.questions.filter(question_type=ExamQuestion.QuestionType.SHORT_ANSWER))
        if not short_answers:
            return
        numbers = {q.number for q in short_answers}
        payload = exam_ai.grade_payload(short_answers)
        grades = self._ai(exam_ai.GRADE_PATH, payload, lambda body: exam_ai.parse_grades(body, numbers))
        for question in short_answers:
            question.is_correct = grades[question.number]
        ExamQuestion.objects.bulk_update(short_answers, ['is_correct'])

    # 5. 점수
    def _score(self):
        correct = self.exam.questions.filter(is_correct=True).count()
        self.exam.correct_count = correct
        self.exam.score = round(correct * 100 / self.exam.question_count)
        self.exam.status = Exam.Status.COMPLETED
        self.exam.completed_at = timezone.now()
        self.exam.save(update_fields=['correct_count', 'score', 'status', 'completed_at'])

    # 6. 성장보고서
    def _write_report(self):
        if Report.objects.filter(lesson=self.lesson).exists():
            return
        term_ids = set(self.lesson.lesson_terms.values_list('term_id', flat=True))
        payload = exam_ai.report_payload(self.lesson, self.exam)
        strengths, recommendations = self._ai(
            exam_ai.REPORT_PATH, payload, lambda body: exam_ai.parse_report(body, term_ids),
        )
        Report.objects.create(
            lesson=self.lesson, score=self.exam.score,
            strengths=strengths, review_recommendations=recommendations,
        )


def _ms(started):
    return int((time.monotonic() - started) * 1000)
