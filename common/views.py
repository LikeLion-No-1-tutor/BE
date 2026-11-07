"""DRF 밖에서 나는 404·500도 공통 에러 형식으로 돌려줍니다 (DEBUG=False일 때 Django가 부름)."""
from django.http import JsonResponse

from .exceptions import error_body
from .middleware import get_request_id


def not_found(request, exception=None):
    return JsonResponse(error_body('NOT_FOUND', '찾을 수 없어요.', get_request_id(request)), status=404)


def server_error(request):
    return JsonResponse(
        error_body('INTERNAL_SERVER_ERROR', '잠시 문제가 생겼어요.', get_request_id(request)), status=500
    )
