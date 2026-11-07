import uuid


class RequestIDMiddleware:
    """요청마다 UUID를 만들어 request.request_id에 두고, 모든 응답의 X-Request-ID 헤더로 돌려줍니다.

    에러 응답의 request_id와 로그도 이 값을 씁니다 (공통 규칙 '요청 ID').
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = str(uuid.uuid4())
        response = self.get_response(request)
        response['X-Request-ID'] = request.request_id
        return response


def get_request_id(request):
    """DRF Request와 Django HttpRequest 모두에서 요청 ID를 꺼냅니다."""
    request_id = getattr(request, 'request_id', None) if request is not None else None
    return request_id or str(uuid.uuid4())
