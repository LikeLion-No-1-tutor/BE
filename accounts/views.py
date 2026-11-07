from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.settings import api_settings as jwt_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

from common.exceptions import ApiError
from materials import storage as material_storage
from materials.models import Material

from .serializers import GoogleLoginRequestSerializer, MeResponseSerializer, UserResponseSerializer

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


def _validation_error(message):
    return ApiError(status.HTTP_400_BAD_REQUEST, 'VALIDATION_ERROR', message)


def _required_refresh_token(request):
    token = request.data.get('refresh_token') if hasattr(request.data, 'get') else None
    if not isinstance(token, str) or not token:
        raise _validation_error('refresh_token이 필요해요.')
    return token


def _blacklist_once(jti):
    """refresh 토큰을 블랙리스트에 넣습니다. 이미 들어 있었거나 발급 기록이 없으면 False.

    같은 토큰으로 동시에 요청이 와도 한 번만 성공하도록 발급 기록 행을 잠그고 처리합니다.
    트랜잭션 안에서 불러야 합니다.
    """
    outstanding = OutstandingToken.objects.select_for_update().filter(jti=jti).first()
    if outstanding is None:
        return False
    _, created = BlacklistedToken.objects.get_or_create(token=outstanding)
    return created


class TokenRefreshView(APIView):
    """02. 토큰 재발급 — POST /api/auth/refresh

    새 access·refresh 토큰을 주고, 쓴 refresh 토큰은 블랙리스트에 넣습니다.
    """

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        token = _required_refresh_token(request)

        try:
            # 서명, 만료, 블랙리스트 여부를 검사
            refresh = RefreshToken(token)
        except TokenError:
            raise _unauthorized('다시 로그인해 주세요.')

        user = User.objects.filter(pk=refresh.payload.get(jwt_settings.USER_ID_CLAIM)).first()
        if user is None:
            raise _unauthorized('다시 로그인해 주세요.')

        with transaction.atomic():
            if not _blacklist_once(refresh.payload[jwt_settings.JTI_CLAIM]):
                # 이미 쓴 토큰 (동시에 두 번 보낸 경우 포함)
                raise _unauthorized('다시 로그인해 주세요.')
            new_refresh = RefreshToken.for_user(user)  # 발급 기록(OutstandingToken)도 남음

        return Response(
            {'access_token': str(new_refresh.access_token), 'refresh_token': str(new_refresh)},
            status=status.HTTP_200_OK,
        )


class LogoutView(APIView):
    """03. 로그아웃 — POST /api/auth/logout

    refresh 토큰을 블랙리스트에 넣습니다. 잘못됐거나, 이미 폐기됐거나, 다른 사용자의 토큰이어도
    결과는 '로그아웃됨'과 같으므로 204를 돌려줍니다 (다른 사용자의 토큰은 건드리지 않음).
    """

    permission_classes = [IsAuthenticated]  # 닉네임 없이도 로그아웃 가능

    def post(self, request):
        token = _required_refresh_token(request)

        try:
            refresh = RefreshToken(token)
        except TokenError:
            return Response(status=status.HTTP_204_NO_CONTENT)

        if str(refresh.payload.get(jwt_settings.USER_ID_CLAIM)) == str(request.user.pk):
            with transaction.atomic():
                _blacklist_once(refresh.payload[jwt_settings.JTI_CLAIM])

        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """04. 내 정보 (GET), 05. 닉네임 저장·온보딩 완료 처리 (PATCH), 06. 회원 탈퇴 (DELETE)
    — /api/users/me
    """

    permission_classes = [IsAuthenticated]  # 닉네임을 저장하기 전에도 써야 하는 API

    def get(self, request):
        return Response(MeResponseSerializer(request.user).data, status=status.HTTP_200_OK)

    def patch(self, request):
        data = request.data if isinstance(request.data, dict) else {}
        user = request.user
        update_fields = []

        if 'nickname' not in data and 'onboarding_completed' not in data:
            raise _validation_error('바꿀 값을 보내 주세요.')

        if 'nickname' in data:
            nickname = data['nickname']
            if not isinstance(nickname, str) or not 1 <= len(nickname.strip()) <= 10:
                raise _validation_error('닉네임은 1~10자여야 해요.')
            user.nickname = nickname.strip()
            update_fields.append('nickname')

        if 'onboarding_completed' in data:
            if data['onboarding_completed'] is not True:
                raise _validation_error('onboarding_completed는 true만 보낼 수 있어요.')
            if user.onboarding_completed_at is None:  # 이미 완료했으면 처음 시각을 그대로 둠
                user.onboarding_completed_at = timezone.now()
                update_fields.append('onboarding_completed_at')

        if update_fields:
            user.save(update_fields=update_fields)

        return Response(MeResponseSerializer(user).data, status=status.HTTP_200_OK)

    def delete(self, request):
        user = request.user

        # 정리 중이던 자료: 커밋 뒤 임시 저장소의 원본을 지움 (돌고 있던 작업은 자료가 없으면 조용히 끝남)
        processing_ids = list(
            Material.objects.filter(user=user, status=Material.Status.PROCESSING).values_list('id', flat=True)
        )

        with transaction.atomic():
            # 다른 기기에서 받은 refresh 토큰까지 모두 블랙리스트에 넣음.
            # OutstandingToken.user는 SET_NULL이라 사용자를 지워도 블랙리스트는 남음.
            not_blacklisted = OutstandingToken.objects.filter(user=user, blacklistedtoken__isnull=True)
            BlacklistedToken.objects.bulk_create(
                [BlacklistedToken(token=token) for token in not_blacklisted],
                ignore_conflicts=True,
            )
            # 학습 데이터(materials, lessons 등)는 FK CASCADE로 함께 지워짐
            user.delete()
            transaction.on_commit(lambda: [material_storage.delete(i) for i in processing_ids])

        return Response(status=status.HTTP_204_NO_CONTENT)
