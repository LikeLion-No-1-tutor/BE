from rest_framework import status
from rest_framework.permissions import BasePermission

from .errors import ApiError


class NicknameRequired(BasePermission):
    """닉네임을 저장하기 전에는 쓸 수 없는 API에 붙입니다 (07번 이후 전부).

    기본 권한(settings의 DEFAULT_PERMISSION_CLASSES)에 들어 있어서 따로 붙이지 않아도 됩니다.
    닉네임 없이 써야 하는 API(03~06번)는 view에서 permission_classes = [IsAuthenticated]로 뺍니다.
    로그인하지 않은 요청은 IsAuthenticated가 먼저 401로 막으므로 여기서는 통과시킵니다.
    """

    def has_permission(self, request, view):
        user = request.user
        if user and user.is_authenticated and not user.nickname:
            raise ApiError(status.HTTP_409_CONFLICT, 'NICKNAME_REQUIRED', '닉네임을 먼저 저장해 주세요.')
        return True
