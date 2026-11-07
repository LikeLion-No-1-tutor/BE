"""08. 학습 자료 업로드의 백그라운드 작업 (material_process).

1. PPT·DOCX는 PDF로 변환, 나머지는 그대로
2. AI-1 용어 체크리스트 생성 → terms 저장
3. AI-2 요약정리 생성 → materials.summary 저장
4. 원본 삭제 (성공·실패 상관없이 항상) → original_deleted_at
5. status: ready, processed_at. 실패하면 status: failed, error

AI 호출은 실패하면 한 번 다시 시도합니다 (UNREADABLE_MATERIAL은 다시 시도하지 않음).
작업 중에 사용자가 탈퇴해 자료가 사라지면 조용히 끝냅니다.
"""
import json
import logging
import mimetypes
import time
from pathlib import Path

from django.db import IntegrityError, transaction
from django.utils import timezone

from common import ai_client
from common.ai_client import AiError

from . import storage
from .conversion import CONVERT_TO_PDF_EXTS, convert_to_pdf
from .models import Material, Term

logger = logging.getLogger(__name__)

JOB = 'material_process'


class MaterialGone(Exception):
    """작업 중에 자료가 지워짐 (회원 탈퇴)"""


def material_process(material_id, request_id):
    started = time.monotonic()
    log_extra = {'job': JOB, 'target_id': material_id, 'request_id': request_id}
    logger.info('job started', extra={'event': 'job_started', **log_extra})

    step = 'read'
    error = None
    try:
        material = _get_material(material_id)
        path = storage.find_original(material_id)
        if path is None:
            raise AiError('AI_ERROR', '임시 저장소에 원본이 없어요.', 'ORIGINAL_NOT_FOUND')

        if material.source_type == Material.SourceType.FILE and material.file_ext in CONVERT_TO_PDF_EXTS:
            step = 'convert'
            path = convert_to_pdf(path)

        step = 'terms'
        terms = _with_retry(lambda: _request_terms(material, path, request_id))
        _save_terms(material_id, terms)

        step = 'summary'
        summary = _with_retry(lambda: _request_summary(material, path, terms, request_id))
        _update(material_id, summary=summary)

    except MaterialGone:
        storage.delete(material_id)
        logger.info('job finished: material deleted', extra={'event': 'job_finished', **log_extra})
        return
    except AiError as ai_error:
        error = ai_error

    # 4. 원본 삭제 (항상)
    storage.delete(material_id)
    now = timezone.now()
    duration_ms = int((time.monotonic() - started) * 1000)

    try:
        if error is None:
            _update(material_id, original_deleted_at=now, status=Material.Status.READY, processed_at=now)
            logger.info('job finished', extra={'event': 'job_finished', 'duration_ms': duration_ms, **log_extra})
        else:
            _update(
                material_id,
                original_deleted_at=now,
                status=Material.Status.FAILED,
                error=error.as_error_json(request_id),
            )
            logger.error(
                'job failed',
                extra={
                    'event': 'job_failed', 'duration_ms': duration_ms, 'step': step,
                    'error_code': error.original_code, **log_extra,
                },
            )
    except MaterialGone:
        logger.info('job finished: material deleted', extra={'event': 'job_finished', **log_extra})


def _get_material(material_id):
    material = Material.objects.filter(pk=material_id).first()
    if material is None:
        raise MaterialGone()
    return material


def _update(material_id, **fields):
    if not Material.objects.filter(pk=material_id).update(**fields):
        raise MaterialGone()


def _save_terms(material_id, terms):
    try:
        with transaction.atomic():
            _get_material(material_id)
            Term.objects.filter(material_id=material_id).delete()
            Term.objects.bulk_create([
                Term(material_id=material_id, name=t['name'], definition=t['definition'], display_order=i)
                for i, t in enumerate(terms, start=1)
            ])
    except IntegrityError:
        # 저장하는 사이에 자료가 지워짐
        raise MaterialGone()


def _with_retry(func):
    try:
        return func()
    except AiError as error:
        if not error.retryable:
            raise
        logger.warning('ai call retry', extra={'event': 'ai_retry', 'error_code': error.original_code})
        return func()


def _multipart(material, path):
    """AI-1·AI-2 공통 필드: title + file 또는 text"""
    data = {'title': material.title}
    if material.source_type == Material.SourceType.TEXT:
        data['text'] = path.read_text(encoding='utf-8')
        return data, None
    if material.file_ext in CONVERT_TO_PDF_EXTS:
        # 변환한 PDF를 보냄: 원래 이름에 확장자만 .pdf로
        file_name = Path(material.file_name or 'material').stem + '.pdf'
    else:
        file_name = material.file_name or path.name
    content_type = mimetypes.guess_type(file_name)[0] or 'application/octet-stream'
    return data, (file_name, content_type)


def _post_material(path_on_ai, material, path, request_id, extra_data=None):
    data, file_info = _multipart(material, path)
    data.update(extra_data or {})
    user_id = material.user_id
    if file_info is None:
        return ai_client.call(path_on_ai, request_id=request_id, user_id=user_id, data=data)
    file_name, content_type = file_info
    with open(path, 'rb') as fh:
        return ai_client.call(
            path_on_ai, request_id=request_id, user_id=user_id,
            data=data, files={'file': (file_name, fh, content_type)},
        )


def _request_terms(material, path, request_id):
    """AI-1 용어 체크리스트 생성"""
    body = _post_material('/materials/terms', material, path, request_id)
    terms = body.get('terms')
    valid = [
        {'name': str(t['name']).strip()[:100], 'definition': str(t['definition']).strip()}
        for t in (terms if isinstance(terms, list) else [])
        if isinstance(t, dict) and str(t.get('name', '')).strip() and str(t.get('definition', '')).strip()
    ]
    if not valid:
        raise AiError('AI_ERROR', '용어 체크리스트가 비어 있어요.', 'INVALID_RESPONSE')
    return valid


def _request_summary(material, path, terms, request_id):
    """AI-2 요약정리 생성"""
    body = _post_material(
        '/materials/summary', material, path, request_id,
        extra_data={'terms': json.dumps(terms, ensure_ascii=False)},
    )
    summary = body.get('summary')
    if not isinstance(summary, str) or not summary.strip():
        raise AiError('AI_ERROR', '요약정리가 비어 있어요.', 'INVALID_RESPONSE')
    return summary
