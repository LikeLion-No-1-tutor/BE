"""로그인과 내 정보 API의 문서 (Swagger). API 동작에는 쓰지 않습니다."""
from rest_framework import serializers

from common.docs import LOGIN, NO_CONTENT, errors, operation

from .serializers import GoogleLoginRequestSerializer, MeResponseSerializer, UserResponseSerializer

AUTH = '인증'
USER = '내 정보'


class GoogleLoginResponse(serializers.Serializer):
    access_token = serializers.CharField(help_text='API를 부를 때 `Authorization: Bearer <access_token>`. 2시간')
    refresh_token = serializers.CharField(help_text='토큰 재발급에 씀. 7일')
    is_new_user = serializers.BooleanField(help_text='이번 로그인으로 가입했으면 true')
    user = UserResponseSerializer()


class RefreshTokenRequest(serializers.Serializer):
    refresh_token = serializers.CharField()


class TokenPairResponse(serializers.Serializer):
    access_token = serializers.CharField()
    refresh_token = serializers.CharField(help_text='새 refresh 토큰. 보낸 토큰은 다시 쓸 수 없음')


class MeUpdateRequest(serializers.Serializer):
    nickname = serializers.CharField(required=False, help_text='앞뒤 공백을 지운 뒤 1~10자')
    onboarding_completed = serializers.BooleanField(required=False, help_text='true만 보낼 수 있음')


google_login = operation(
    'google_login', AUTH, '구글 로그인과 회원가입',
    description='구글에서 받은 ID 토큰으로 로그인합니다. 처음이면 가입합니다. 닉네임이 없으면 닉네임 저장부터 해야 합니다.',
    request=GoogleLoginRequestSerializer,
    responses={200: GoogleLoginResponse, **errors(s400=['VALIDATION_ERROR'], s401=['UNAUTHORIZED'])},
)

token_refresh = operation(
    'token_refresh', AUTH, '토큰 재발급',
    description='새 access 토큰과 refresh 토큰을 줍니다. 보낸 refresh 토큰은 폐기됩니다. 401이면 다시 로그인합니다.',
    request=RefreshTokenRequest,
    responses={200: TokenPairResponse, **errors(s400=['VALIDATION_ERROR'], s401=['UNAUTHORIZED'])},
)

logout = operation(
    'logout', AUTH, '로그아웃',
    description='refresh 토큰을 폐기합니다. 이미 폐기됐거나 잘못된 토큰이어도 204입니다. 닉네임이 없어도 됩니다.',
    request=RefreshTokenRequest,
    responses={204: NO_CONTENT, **errors(LOGIN, s400=['VALIDATION_ERROR'])},
)

me = operation(
    'me', USER, '내 정보',
    description='닉네임이 없어도 됩니다.',
    responses={200: MeResponseSerializer, **errors(LOGIN)},
)

me_update = operation(
    'me_update', USER, '닉네임 저장과 온보딩 완료',
    description='`nickname`, `onboarding_completed` 중 하나 이상을 보냅니다. 닉네임이 없어도 됩니다.',
    request=MeUpdateRequest,
    responses={200: MeResponseSerializer, **errors(LOGIN, s400=['VALIDATION_ERROR'])},
)

me_delete = operation(
    'me_delete', USER, '회원 탈퇴',
    description='모든 학습 데이터를 지우고 발급한 refresh 토큰을 모두 폐기합니다.',
    responses={204: NO_CONTENT, **errors(LOGIN)},
)
