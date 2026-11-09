import logging
import time
import uuid

from .json_log import request_id_var

logger = logging.getLogger('common.request')


class RequestIDMiddleware:
    """요청마다 UUID를 만들어 request.request_id에 두고, 모든 응답의 X-Request-ID 헤더로 돌려줍니다.

    에러 응답의 request_id와 로그도 이 값을 씁니다 (공통 규칙 '요청 ID').
    요청이 끝나면 http_request 로그를 한 줄 남깁니다.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = str(uuid.uuid4())
        token = request_id_var.set(request.request_id)
        started = time.monotonic()
        try:
            response = self.get_response(request)
            response['X-Request-ID'] = request.request_id
            _log_request(request, response, started)
            return response
        finally:
            request_id_var.reset(token)


def _log_request(request, response, started):
    status = response.status_code
    if status >= 500:
        level = logging.ERROR
    elif status >= 400 and status != 401:
        level = logging.WARNING
    else:
        level = logging.INFO
    extra = {
        'event': 'http_request',
        'request_id': request.request_id,
        'method': request.method,
        'path': request.path,  # 쿼리 문자열은 넣지 않음
        'status': status,
        'duration_ms': int((time.monotonic() - started) * 1000),
        'user_id': _user_id(request),
    }
    error_code = getattr(request, 'error_code', None)
    if error_code:
        extra['error_code'] = error_code
    logger.log(level, '%s %s %s', request.method, request.path, status, extra=extra)


def _user_id(request):
    try:
        user = getattr(request, 'user', None)
        return user.pk if user is not None and user.is_authenticated else None
    except Exception:  # 로그 때문에 요청이 실패하면 안 됨
        return None


def remember_error_code(request, code):
    """응답의 에러 code를 http_request 로그에 남길 수 있게 기억합니다."""
    if request is not None:
        getattr(request, '_request', request).error_code = code


def get_request_id(request):
    """DRF Request와 Django HttpRequest 모두에서 요청 ID를 꺼냅니다."""
    request_id = getattr(request, 'request_id', None) if request is not None else None
    return request_id or str(uuid.uuid4())
