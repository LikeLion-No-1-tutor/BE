import uuid
from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status

def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    request = context.get('request')
    
    request_id = str(uuid.uuid4())

    # 프레임워크가 잡지 못한 500 에러 처리
    if response is None:
        return Response(
            {
                "error": {
                    "code": "INTERNAL_SERVER_ERROR",
                    "message": "잠시 문제가 생겼어요.",
                    "request_id": request_id
                }
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            headers={'X-Request-ID': request_id}
        )

    return response