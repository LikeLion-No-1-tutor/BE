"""AI 서버(FastAPI) 호출 (공통 규칙 (AI 파트 API)).

- 헤더: X-Internal-Token, X-Request-ID
- 실패하면 AiError를 던집니다. code는 프론트엔드에 전하는 code(AI_ERROR, UNREADABLE_MATERIAL)이고,
  AI 서버의 원래 code는 original_code로 로그에만 남깁니다.
- 요청·응답 본문(원본 자료, AI가 만든 내용)은 로그에 남기지 않습니다.
"""
import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

BACKGROUND_TIMEOUT = 180  # 초. AI 서버의 LLM 타임아웃(170초)보다 길게
REALTIME_TIMEOUT = 30


class AiError(Exception):
    def __init__(self, code, message, original_code):
        super().__init__(message)
        self.code = code  # AI_ERROR 또는 UNREADABLE_MATERIAL
        self.message = message
        self.original_code = original_code  # LLM_TIMEOUT 등 (로그용)

    @property
    def retryable(self):
        return self.code == 'AI_ERROR'

    def as_error_json(self, request_id):
        """materials·lessons·exams 테이블의 error 컬럼에 저장할 값"""
        messages = {
            'AI_ERROR': 'AI 처리에 실패했어요.',
            'UNREADABLE_MATERIAL': '자료에서 내용을 읽을 수 없어요.',
        }
        return {'code': self.code, 'message': messages.get(self.code, self.message), 'request_id': request_id}


def call(path, *, request_id, user_id=None, json=None, data=None, files=None, timeout=BACKGROUND_TIMEOUT):
    """AI 서버를 한 번 부르고 응답 JSON을 돌려줍니다."""
    base_url = getattr(settings, 'AI_SERVER_URL', '')
    token = getattr(settings, 'AI_SERVER_TOKEN', '')
    if not base_url or not token:
        _log(path, request_id, user_id, status=None, started=time.monotonic(), error_code='AI_SERVER_NOT_CONFIGURED')
        raise AiError('AI_ERROR', 'AI_SERVER_URL 또는 AI_SERVER_TOKEN이 설정되지 않았어요.', 'AI_SERVER_NOT_CONFIGURED')

    started = time.monotonic()
    try:
        response = requests.post(
            base_url.rstrip('/') + path,
            headers={'X-Internal-Token': token, 'X-Request-ID': request_id},
            json=json,
            data=data,
            files=files,
            timeout=timeout,
        )
    except requests.Timeout:
        _log(path, request_id, user_id, status=None, started=started, error_code='DJANGO_TIMEOUT')
        raise AiError('AI_ERROR', 'AI 서버 응답 시간이 초과됐어요.', 'DJANGO_TIMEOUT')
    except requests.RequestException as error:
        _log(path, request_id, user_id, status=None, started=started, error_code=type(error).__name__)
        raise AiError('AI_ERROR', 'AI 서버에 연결하지 못했어요.', type(error).__name__)

    try:
        body = response.json()
    except ValueError:
        body = None  # JSON이 아님

    if response.status_code != 200:
        # 에러 본문이 약속한 모양({"error": {"code", "message"}})이 아니어도 처리할 수 있게
        error = body.get('error') if isinstance(body, dict) else None
        error = error if isinstance(error, dict) else {}
        original = error.get('code') if isinstance(error.get('code'), str) else f'HTTP_{response.status_code}'
        message = error.get('message') if isinstance(error.get('message'), str) else 'AI 처리에 실패했어요.'
        _log(path, request_id, user_id, status=response.status_code, started=started, error_code=original)
        code = 'UNREADABLE_MATERIAL' if original == 'UNREADABLE_MATERIAL' else 'AI_ERROR'
        raise AiError(code, message, original)

    if not isinstance(body, dict):
        # 200인데 JSON 객체가 아님 (배열, null, JSON이 아닌 본문 등)
        _log(path, request_id, user_id, status=200, started=started, error_code='INVALID_RESPONSE')
        raise AiError('AI_ERROR', 'AI 서버 응답이 JSON 객체가 아니에요.', 'INVALID_RESPONSE')

    _log(path, request_id, user_id, status=200, started=started, usage=body.get('usage'))
    return body


def _log(path, request_id, user_id, *, status, started, error_code=None, usage=()):
    usage = [u for u in usage if isinstance(u, dict)] if isinstance(usage, list) else []
    extra = {
        'event': 'ai_call',
        'request_id': request_id,
        'ai_path': path,
        'status': status,
        'duration_ms': int((time.monotonic() - started) * 1000),
        'user_id': user_id,
        'input_tokens': sum(_count(u.get('input_tokens')) for u in usage),
        'output_tokens': sum(_count(u.get('output_tokens')) for u in usage),
    }
    if error_code:
        extra['error_code'] = error_code
        logger.warning('ai_call %s failed: %s', path, error_code, extra=extra)
    else:
        logger.info('ai_call %s ok', path, extra=extra)


def _count(value):
    """토큰 수. 숫자가 아니면 0 (usage는 로그에만 쓰므로 작업을 실패시키지 않음)"""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
