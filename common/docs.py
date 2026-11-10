"""API 문서(Swagger)에서 같이 쓰는 모양과 도구.

API 동작에는 쓰지 않고 문서에만 씁니다. 앱마다 docs.py에 응답 모양과 extend_schema를 두고,
views.py에서는 데코레이터 한 줄로 붙입니다.
"""
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import serializers

from .docs_examples import ERROR_MESSAGES, REQUEST_ID
from .pagination import DEFAULT_SIZE, MAX_SIZE


class ErrorBody(serializers.Serializer):
    code = serializers.CharField(help_text='에러 코드. 예) VALIDATION_ERROR')
    message = serializers.CharField(help_text='사용자에게 보여 줄 수 있는 문장')
    request_id = serializers.CharField(help_text='응답 헤더 X-Request-ID와 같은 값')


class ErrorResponse(serializers.Serializer):
    """모든 에러 응답의 공통 모양"""
    error = ErrorBody()


class StoredError(serializers.Serializer):
    """백그라운드 작업이 실패했을 때 저장해 둔 에러 (자료, 수업, 재시험의 error)"""
    code = serializers.CharField(help_text='AI_ERROR 또는 UNREADABLE_MATERIAL')
    message = serializers.CharField()
    request_id = serializers.CharField(allow_null=True)


_STATUS_TEXT = {
    400: '요청 값이 올바르지 않음',
    401: '로그인 필요 또는 토큰 만료',
    403: '다른 사용자의 데이터',
    404: '없는 데이터',
    409: '지금 상태에서는 할 수 없음',
    413: '파일이나 텍스트가 너무 큼',
    502: 'AI 서버 호출 실패. 아무것도 저장하지 않음',
}

# 기본 권한(로그인 + 닉네임)을 쓰는 API의 공통 에러
LOGIN = {401: ['UNAUTHORIZED']}
MEMBER = {401: ['UNAUTHORIZED'], 409: ['NICKNAME_REQUIRED']}
OWNED = {**MEMBER, 403: ['FORBIDDEN'], 404: ['NOT_FOUND']}


def errors(*groups, **extra):
    """상태 코드별 에러 코드를 모아 OpenAPI 응답으로 만듭니다.

    errors(OWNED, s409=['LESSON_NOT_TEACHING'], s502=['AI_ERROR'])
    """
    codes = {}
    for group in groups + ({int(key[1:]): value for key, value in extra.items()},):
        for status_code, names in group.items():
            codes.setdefault(status_code, [])
            codes[status_code] += [name for name in names if name not in codes[status_code]]
    return {
        status_code: OpenApiResponse(
            ErrorResponse,
            description=f"{_STATUS_TEXT[status_code]}: {', '.join(f'`{name}`' for name in names)}",
            examples=[
                OpenApiExample(
                    name,
                    summary=name,  # Swagger의 예시 선택 목록에 코드 그대로 보이게
                    value={'error': {'code': name, 'message': ERROR_MESSAGES[name], 'request_id': REQUEST_ID}},
                    response_only=True,
                    status_codes=[str(status_code)],
                )
                for name in names
            ],
        )
        for status_code, names in sorted(codes.items())
    }


def paged(item, name):
    """PagePagination 응답 모양. {"items": [...], "page", "size", "total"}"""
    return type(name, (serializers.Serializer,), {
        'items': item(many=True),
        'page': serializers.IntegerField(),
        'size': serializers.IntegerField(),
        'total': serializers.IntegerField(help_text='전체 개수'),
        '__doc__': f'{item.__name__} 목록 한 페이지',
    })


PAGE_PARAMETERS = [
    OpenApiParameter('page', int, default=1, description='1부터 시작. 마지막 페이지를 넘으면 items가 빈 배열'),
    OpenApiParameter('size', int, default=DEFAULT_SIZE, description=f'최대 {MAX_SIZE}. 최대보다 크면 최대로 줄임'),
]

NO_CONTENT = OpenApiResponse(description='본문 없음')


def operation(operation_id, tag, summary, *, request=None, responses, description='', parameters=None):
    """extend_schema에 이 프로젝트에서 늘 같은 값을 채워 줍니다.

    request에 serializer만 주면 JSON 본문으로 적습니다. (DRF 기본 설정상 폼 형식도 받지만 프론트엔드는 JSON을 씀)
    """
    if request is not None and not isinstance(request, dict):
        request = {'application/json': request}
    return extend_schema(
        operation_id=operation_id,
        tags=[tag],
        summary=summary,
        description=description,
        request=request,
        responses=responses,
        parameters=parameters,
    )
