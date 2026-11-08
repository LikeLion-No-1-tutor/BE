from rest_framework.pagination import BasePagination
from rest_framework.response import Response

from .errors import ApiError

DEFAULT_SIZE = 20
MAX_SIZE = 100


class PagePagination(BasePagination):
    """?page=1&size=20 → {"items": [...], "page": 1, "size": 20, "total": 42}

    공통 규칙 (백엔드 API) '목록'.
    - page, size가 1 이상의 정수가 아니면 400 VALIDATION_ERROR
    - size는 최대 100. 넘으면 100으로 줄인다
    - 마지막 페이지를 넘으면 items가 빈 배열 (404가 아님)
    """

    def paginate_queryset(self, queryset, request, view=None):
        self.page = _positive_int(request.query_params.get('page'), default=1)
        self.size = min(_positive_int(request.query_params.get('size'), default=DEFAULT_SIZE), MAX_SIZE)
        self.total = queryset.count()
        start = (self.page - 1) * self.size
        return list(queryset[start:start + self.size])

    def get_paginated_response(self, data):
        return Response({'items': data, 'page': self.page, 'size': self.size, 'total': self.total})


def _positive_int(value, default):
    if value in (None, ''):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    if number < 1:
        raise ApiError(400, 'VALIDATION_ERROR', 'page와 size는 1 이상의 정수여야 해요.')
    return number
