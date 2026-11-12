"""08. 학습 자료 업로드의 백그라운드 작업 (material_process).

1. PPT·DOCX는 PDF로 변환, 나머지는 그대로
2. AI-1 용어 체크리스트 생성 → terms 저장
3. AI-2 요약정리 생성 → materials.summary 저장
4. 원본 삭제 (성공·실패 상관없이 항상) → original_deleted_at
5. status: ready, processed_at. 실패하면 status: failed, error

AI 호출은 ai_client가 실패하면 한 번 다시 부릅니다 (UNREADABLE_MATERIAL은 다시 부르지 않음).
작업 중에 사용자가 탈퇴해 자료가 사라지면 조용히 끝냅니다.
예상하지 못한 예외가 나도 원본은 반드시 지우고, 자료는 failed(AI_ERROR)로 끝냅니다.
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

# Python 3.12의 기본 목록에는 WebP가 없어서 서버의 /etc/mime.types에 따라 달라짐. 항상 같은 형식으로 보내도록 등록
mimetypes.add_type('image/webp', '.webp')

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
        terms = _request_terms(material, path, request_id)
        _save_terms(material_id, terms)

        step = 'summary'
        summary = _request_summary(material, path, terms, request_id)
        _update(material_id, summary=summary)

    except MaterialGone:
        logger.info('job finished: material deleted', extra={'event': 'job_finished', **log_extra})
        return
    except AiError as ai_error:
        error = ai_error
    except Exception as unexpected:
        # 코드 버그, 파일 읽기 실패, DB 오류 등. 자료가 processing에 멈추지 않게 실패로 끝냄
        logger.exception(
            'job crashed',
            extra={'event': 'exception', 'step': step, 'exception_type': type(unexpected).__name__, **log_extra},
        )
        error = AiError('AI_ERROR', '자료 정리 중 예상하지 못한 오류가 났어요.', 'UNEXPECTED')
    finally:
        # 4. 원본 삭제 (성공·실패·탈퇴 상관없이 항상)
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


def _multipart(material, path):
    """자료 정리 AI 호출 공통: 제목은 폼 필드로, 자료는 파일로 보냅니다.

    직접 입력한 텍스트도 파일로 보냅니다. 폼 필드로 보내면 AI 서버가 약 1MB에서 거절합니다.
    """
    data = {'title': material.title}
    if material.source_type == Material.SourceType.TEXT:
        return data, ('material.txt', 'text/plain')
    if material.file_ext in CONVERT_TO_PDF_EXTS:
        # 변환한 PDF를 보냄: 원래 이름에 확장자만 .pdf로
        file_name = Path(material.file_name or 'material').stem + '.pdf'
    else:
        file_name = material.file_name or path.name
    content_type = mimetypes.guess_type(file_name)[0] or 'application/octet-stream'
    return data, (file_name, content_type)


def _post_material(path_on_ai, material, path, request_id, parse, extra_data=None):
    data, file_info = _multipart(material, path)
    data.update(extra_data or {})
    user_id = material.user_id
    file_name, content_type = file_info
    with open(path, 'rb') as fh:
        return ai_client.call(
            path_on_ai, request_id=request_id, user_id=user_id,
            data=data, files={'file': (file_name, fh, content_type)}, parse=parse,
        )


def _request_terms(material, path, request_id):
    """AI-1 용어 체크리스트 생성"""
    return _post_material('/materials/terms', material, path, request_id, _parse_terms)


def _parse_terms(body):
    terms = body.get('terms')
    valid = [
        {'name': str(t['name']).strip()[:100], 'definition': str(t['definition']).strip()}
        for t in (terms if isinstance(terms, list) else [])
        if isinstance(t, dict) and str(t.get('name', '')).strip() and str(t.get('definition', '')).strip()
    ]
    if not valid:
        raise ValueError('용어 체크리스트가 비어 있어요.')
    return valid


def _request_summary(material, path, terms, request_id):
    """AI-2 요약정리 생성"""
    return _post_material(
        '/materials/summary', material, path, request_id, _parse_summary,
        extra_data={'terms': json.dumps(terms, ensure_ascii=False)},
    )


def _parse_summary(body):
    summary = body.get('summary')
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError('요약정리가 비어 있어요.')
    return summary
