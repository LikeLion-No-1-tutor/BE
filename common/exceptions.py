import logging

from django.http import Http404
from rest_framework import exceptions, status
from rest_framework.response import Response
from rest_framework.views import exception_handler

from .errors import ApiError  # noqa: F401  (기존 import 경로 유지: from common.exceptions import ApiError)
from .middleware import get_request_id

logger = logging.getLogger(__name__)


# DRF 기본 예외 → 공통 규칙의 (code, message)
_DEFAULT_ERRORS = [
    ((exceptions.ValidationError, exceptions.ParseError, exceptions.UnsupportedMediaType),
     status.HTTP_400_BAD_REQUEST, 'VALIDATION_ERROR', '요청 형식이 올바르지 않아요.'),
    ((exceptions.NotAuthenticated, exceptions.AuthenticationFailed),
     status.HTTP_401_UNAUTHORIZED, 'UNAUTHORIZED', '로그인이 필요해요.'),
    ((exceptions.PermissionDenied,),
     status.HTTP_403_FORBIDDEN, 'FORBIDDEN', '접근할 수 없는 데이터예요.'),
    ((exceptions.NotFound, Http404),
     status.HTTP_404_NOT_FOUND, 'NOT_FOUND', '찾을 수 없어요.'),
    ((exceptions.MethodNotAllowed,),
     status.HTTP_405_METHOD_NOT_ALLOWED, 'METHOD_NOT_ALLOWED', '지원하지 않는 요청 방식이에요.'),
]


def error_body(code, message, request_id):
    return {'error': {'code': code, 'message': message, 'request_id': request_id}}


def custom_exception_handler(exc, context):
    """모든 에러를 { "error": { code, message, request_id } } 모양으로 바꿉니다."""
    request = context.get('request')
    request_id = get_request_id(request)

    if isinstance(exc, ApiError):
        return Response(error_body(exc.error_code, exc.message, request_id), status=exc.status_code)

    response = exception_handler(exc, context)

    if response is None:
        # 처리하지 못한 예외: 원인을 찾을 수 있게 로그를 남기고 500
        logger.exception(
            'unhandled exception',
            extra={'event': 'exception', 'request_id': request_id, 'exception_type': type(exc).__name__},
        )
        return Response(
            error_body('INTERNAL_SERVER_ERROR', '잠시 문제가 생겼어요.', request_id),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    for exc_types, status_code, code, message in _DEFAULT_ERRORS:
        if isinstance(exc, exc_types):
            response.status_code = status_code
            response.data = error_body(code, message, request_id)
            return response

    # 그 밖의 DRF 예외 (Throttled 등): 상태 코드는 그대로, code는 DRF의 default_code를 대문자로
    code = getattr(exc, 'default_code', 'error').upper()
    response.data = error_body(code, str(getattr(exc, 'detail', '')), request_id)
    return response
