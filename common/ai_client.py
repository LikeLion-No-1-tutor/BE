"""AI 서버(FastAPI) 호출 (공통 규칙 (AI 파트 API)).

- 헤더: X-Internal-Token, X-Request-ID
- 실패하면 AiError를 던집니다. code는 프론트엔드에 전하는 code(AI_ERROR, UNREADABLE_MATERIAL)이고,
  AI 서버의 원래 code는 original_code로 로그에만 남깁니다.
- 요청·응답 본문(원본 자료, AI가 만든 내용)은 로그에 남기지 않습니다.
- mode: REALTIME은 사용자가 기다리는 요청(30초, 다시 부르지 않음),
  BACKGROUND는 백그라운드 작업(180초, 실패하면 한 번 다시 부름. UNREADABLE_MATERIAL과 요청이 거절된 4xx는 다시 불러도 같으므로 제외)
- parse: 응답에서 필요한 값을 꺼내는 함수. 모양이 틀려 ValueError·KeyError·TypeError가 나면
  INVALID_RESPONSE 실패로 보고, 백그라운드면 다시 부릅니다. 주면 parse의 결과를 돌려줍니다.

    # 실시간: 실패하면 502를 그대로 프론트엔드로
    try:
        value = ai_client.call(path, json=payload, request_id=rid, user_id=uid, mode=ai_client.REALTIME, parse=parse)
    except ai_client.AiError as error:
        raise error.to_api_error()

    # 백그라운드: 실패하면 DB의 error 컬럼에 error.as_error_json(request_id)
    value = ai_client.call(path, json=payload, request_id=rid, user_id=uid, parse=parse)
"""
import logging
import time

import requests
from django.conf import settings
from rest_framework import status as http_status

from .errors import ApiError

logger = logging.getLogger(__name__)

REALTIME = 'realtime'
BACKGROUND = 'background'

BACKGROUND_TIMEOUT = 180  # 초. AI 서버의 LLM 타임아웃(170초)보다 길게
REALTIME_TIMEOUT = 30

_TIMEOUTS = {REALTIME: REALTIME_TIMEOUT, BACKGROUND: BACKGROUND_TIMEOUT}
_ATTEMPTS = {REALTIME: 1, BACKGROUND: 2}
# 요청 자체가 거절된 경우. 다시 불러도 결과가 같습니다.
_NOT_RETRYABLE_STATUSES = {400, 401, 403, 404, 422}


class AiError(Exception):
    def __init__(self, code, message, original_code, status=None):
        super().__init__(message)
        self.code = code  # AI_ERROR 또는 UNREADABLE_MATERIAL
        self.message = message
        self.original_code = original_code  # LLM_TIMEOUT 등 (로그용)
        self.status = status  # AI 서버의 HTTP 상태 (응답을 받지 못했으면 None, 로그용)

    @property
    def retryable(self):
        return self.code == 'AI_ERROR' and self.status not in _NOT_RETRYABLE_STATUSES

    def as_error_json(self, request_id):
        """materials·lessons·exams 테이블의 error 컬럼에 저장할 값"""
        messages = {
            'AI_ERROR': 'AI 처리에 실패했어요.',
            'UNREADABLE_MATERIAL': '자료에서 내용을 읽을 수 없어요.',
        }
        return {'code': self.code, 'message': messages.get(self.code, self.message), 'request_id': request_id}

    def to_api_error(self):
        """실시간 요청에서 프론트엔드로 돌려줄 502 에러"""
        return ApiError(http_status.HTTP_502_BAD_GATEWAY, self.code, 'AI 처리에 실패했어요. 다시 시도해 주세요.')


def call(path, *, request_id, user_id=None, json=None, data=None, files=None, mode=BACKGROUND, parse=None):
    """AI 서버를 부르고 응답 JSON(parse를 주면 parse의 결과)을 돌려줍니다. 실패하면 AiError."""
    base_url = getattr(settings, 'AI_SERVER_URL', '')
    token = getattr(settings, 'AI_SERVER_TOKEN', '')
    if not base_url or not token:
        # 설정 문제는 다시 불러도 같음
        _log(path, request_id, user_id, 1, status=None, started=time.monotonic(),
             error_code='AI_SERVER_NOT_CONFIGURED', level=logging.ERROR)
        raise AiError('AI_ERROR', 'AI_SERVER_URL 또는 AI_SERVER_TOKEN이 설정되지 않았어요.', 'AI_SERVER_NOT_CONFIGURED')

    url = base_url.rstrip('/') + path
    headers = {'X-Internal-Token': token, 'X-Request-ID': request_id}
    attempts = _ATTEMPTS[mode]
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            body = _request(url, headers, json, data, files, _TIMEOUTS[mode])
            value = _parse(body, parse)
        except AiError as error:
            will_retry = error.retryable and attempt < attempts
            _log(path, request_id, user_id, attempt, status=error.status, started=started,
                 error_code=error.original_code, level=logging.WARNING if will_retry else logging.ERROR)
            if not will_retry:
                raise
            _rewind(files)
            continue
        _log(path, request_id, user_id, attempt, status=200, started=started, usage=body.get('usage'))
        return value


def _request(url, headers, json, data, files, timeout):
    """한 번 불러 응답 본문(dict)을 돌려줍니다."""
    try:
        response = requests.post(url, headers=headers, json=json, data=data, files=files, timeout=timeout)
    except requests.Timeout:
        raise AiError('AI_ERROR', 'AI 서버 응답 시간이 초과됐어요.', 'DJANGO_TIMEOUT')
    except requests.RequestException as error:
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
        code = 'UNREADABLE_MATERIAL' if original == 'UNREADABLE_MATERIAL' else 'AI_ERROR'
        raise AiError(code, message, original, status=response.status_code)

    if not isinstance(body, dict):
        # 200인데 JSON 객체가 아님 (배열, null, JSON이 아닌 본문 등)
        raise AiError('AI_ERROR', 'AI 서버 응답이 JSON 객체가 아니에요.', 'INVALID_RESPONSE', status=200)
    return body


def _parse(body, parse):
    if parse is None:
        return body
    try:
        return parse(body)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise AiError('AI_ERROR', f'AI 서버 응답 모양이 달라요: {error}', 'INVALID_RESPONSE', status=200) from error


def _rewind(files):
    """다시 부를 때 파일을 처음부터 읽게 합니다."""
    for value in (files or {}).values():
        file_obj = value[1] if isinstance(value, (tuple, list)) else value
        if hasattr(file_obj, 'seek'):
            file_obj.seek(0)


def _log(path, request_id, user_id, attempt, *, status, started, error_code=None, usage=(), level=logging.INFO):
    """성공은 INFO, 다시 부를 실패는 WARNING, 마지막 실패는 ERROR"""
    usage = [u for u in usage if isinstance(u, dict)] if isinstance(usage, list) else []
    extra = {
        'event': 'ai_call',
        'request_id': request_id,
        'ai_path': path,
        'status': status,
        'attempt': attempt,
        'duration_ms': int((time.monotonic() - started) * 1000),
        'user_id': user_id,
        'input_tokens': sum(_count(u.get('input_tokens')) for u in usage),
        'output_tokens': sum(_count(u.get('output_tokens')) for u in usage),
    }
    if error_code:
        extra['error_code'] = error_code
        logger.log(level, 'ai_call %s failed: %s', path, error_code, extra=extra)
    else:
        logger.info('ai_call %s ok', path, extra=extra)


def _count(value):
    """토큰 수. 숫자가 아니면 0 (usage는 로그에만 쓰므로 작업을 실패시키지 않음)"""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0
