"""재시험 출제의 백그라운드 처리 (retest_generate). common.jobs.enqueue로 등록한다.

문제 출제 AI(kind: retest) → exam_questions 저장 → status: solving.
AI 호출은 BACKGROUND 모드라 실패하면 한 번 다시 부르고, 또 실패하면 status: failed, exams.error.
"""
import logging
import time

from django.conf import settings
from django.db import transaction

from common import ai_client
from lessons.models import LessonTerm

from . import ai
from .models import Exam, ExamQuestion

logger = logging.getLogger(__name__)

JOB = 'retest_generate'
FOCUS_MISSED_TERMS = 'missed_terms'
FOCUS_ALL = 'all'
MAX_EXCLUDE_QUESTIONS = 200  # AI 서버가 받는 이전 문제 수의 상한


def run_retest_generate(exam_id, focus, request_id):
    exam = (
        Exam.objects.select_related('lesson__material')
        .filter(pk=exam_id, kind=Exam.Kind.RETEST, status=Exam.Status.GENERATING)
        .first()
    )
    log_fields = {'job': JOB, 'target_id': exam_id, 'request_id': request_id}
    if exam is None:  # 탈퇴로 지워졌거나 이미 처리된 재시험
        logger.warning('retest_generate skipped', extra={'event': 'job_skipped', **log_fields})
        return

    started = time.monotonic()
    logger.info('job started', extra={'event': 'job_started', **log_fields})
    try:
        _generate(exam, focus, request_id)
    except ai_client.AiError as error:
        _fail(exam, error.as_error_json(request_id))
        logger.error('job failed', extra={
            'event': 'job_failed', **log_fields, 'duration_ms': _ms(started),
            'step': 'exam_generate', 'error_code': error.original_code,
        })
        return
    except Exception:
        _fail(exam, ai_client.AiError('AI_ERROR', '예상하지 못한 오류', 'UNEXPECTED').as_error_json(request_id))
        logger.exception('job failed', extra={
            'event': 'job_failed', **log_fields, 'duration_ms': _ms(started),
            'step': 'exam_generate', 'error_code': 'UNEXPECTED',
        })
        raise
    logger.info('job finished', extra={'event': 'job_finished', **log_fields, 'duration_ms': _ms(started)})


def _generate(exam, focus, request_id):
    lesson = exam.lesson
    material = lesson.material
    term_ids = set(material.terms.values_list('id', flat=True))
    focus_term_ids = []
    if focus == FOCUS_MISSED_TERMS:
        focus_term_ids = list(
            lesson.lesson_terms.exclude(status=LessonTerm.Status.EXPLAINED).values_list('term_id', flat=True)
        )
    # 이 수업에서 이미 낸 문제는 또 내지 않게
    latest = ExamQuestion.objects.filter(exam__lesson=lesson).order_by('-exam_id', '-number')
    exclude_questions = list(latest.values_list('content', flat=True)[:MAX_EXCLUDE_QUESTIONS])[::-1]
    payload = ai.generate_payload(
        material, Exam.Kind.RETEST, exam.question_count, settings.EXAM_QUESTION_TYPES,
        focus_term_ids=focus_term_ids, exclude_questions=exclude_questions,
    )
    questions = ai_client.call(
        ai.GENERATE_PATH, json=payload, request_id=request_id, mode=ai_client.BACKGROUND,
        user_id=lesson.user_id, parse=lambda body: ai.parse_generated(body, term_ids),
    )
    with transaction.atomic():
        exam = Exam.objects.select_for_update().get(pk=exam.pk)
        if exam.status != Exam.Status.GENERATING:
            return
        ExamQuestion.objects.bulk_create(ExamQuestion(exam=exam, **q) for q in questions)
        exam.question_count = len(questions)
        exam.status = Exam.Status.SOLVING
        exam.save(update_fields=['question_count', 'status'])


def _fail(exam, error_json):
    Exam.objects.filter(pk=exam.pk, status=Exam.Status.GENERATING).update(status=Exam.Status.FAILED, error=error_json)


def _ms(started):
    return int((time.monotonic() - started) * 1000)
