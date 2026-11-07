from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from common.exceptions import ApiError

from .serializers import GoogleLoginRequestSerializer, UserResponseSerializer

User = get_user_model()

INVALID_GOOGLE_LOGIN = '구글 로그인 정보를 확인할 수 없어요.'


def _unauthorized(message=INVALID_GOOGLE_LOGIN):
    return ApiError(status.HTTP_401_UNAUTHORIZED, 'UNAUTHORIZED', message)


class GoogleLoginView(APIView):
    """01. 소셜 로그인·회원가입 — POST /api/auth/google"""

    authentication_classes = []  # 만료된 Bearer 헤더가 붙어 와도 로그인은 되게
    permission_classes = [AllowAny]

    def post(self, request):
        # 1. 입력값 검증
        serializer = GoogleLoginRequestSerializer(data=request.data)
        if not serializer.is_valid():
            raise ApiError(status.HTTP_400_BAD_REQUEST, 'VALIDATION_ERROR', 'id_token이 필요해요.')

        # 2. 구글 ID 토큰 검증 (서명, 발급자, aud = GOOGLE_CLIENT_ID, 만료)
        try:
            id_info = id_token.verify_oauth2_token(
                serializer.validated_data['id_token'],
                google_requests.Request(),
                settings.GOOGLE_CLIENT_ID,
            )
        except ValueError:
            raise _unauthorized()

        google_sub = id_info.get('sub')
        email = id_info.get('email')
        if not google_sub or not email or id_info.get('email_verified') is not True:
            raise _unauthorized()

        # 3. sub로만 사용자를 찾고, 없으면 새로 만듦 (이메일로 기존 계정에 연결하지 않음)
        user, is_new_user = self._get_or_create_user(google_sub, email)

        # 4. last_login_at 갱신
        user.last_login_at = timezone.now()
        user.save(update_fields=['last_login_at'])

        # 5. JWT 발급
        refresh = RefreshToken.for_user(user)

        return Response(
            {
                'access_token': str(refresh.access_token),
                'refresh_token': str(refresh),
                'is_new_user': is_new_user,
                'user': UserResponseSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )

    @staticmethod
    def _get_or_create_user(google_sub, email):
        user = User.objects.filter(google_sub=google_sub).first()
        if user is not None:
            return user, False

        try:
            with transaction.atomic():
                return User.objects.create_user(email=email, google_sub=google_sub), True
        except IntegrityError:
            # 같은 sub로 동시에 처음 로그인한 경우: 먼저 만들어진 사용자를 씀
            user = User.objects.filter(google_sub=google_sub).first()
            if user is not None:
                return user, False
            # 같은 이메일이 다른 구글 계정(sub)으로 이미 가입돼 있음
            raise _unauthorized('이미 다른 구글 계정으로 가입된 이메일이에요.')
