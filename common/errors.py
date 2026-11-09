from rest_framework import exceptions


class ApiError(exceptions.APIException):
    """명세의 에러 code와 message를 그대로 돌려줄 때 씁니다.

    예) raise ApiError(401, 'UNAUTHORIZED', '구글 로그인 정보를 확인할 수 없어요.')

    rest_framework.views를 import하지 않는 파일에 둡니다. DRF 설정(DEFAULT_PERMISSION_CLASSES)이
    불러오는 common.permissions에서 쓰기 때문에, 여기서 views를 부르면 순환 import가 납니다.
    """

    def __init__(self, status_code, code, message):
        self.status_code = status_code
        self.error_code = code
        self.message = message
        super().__init__(detail=message, code=code)
