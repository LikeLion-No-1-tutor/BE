from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()


class GoogleLoginRequestSerializer(serializers.Serializer):
    id_token = serializers.CharField(required=True)


class UserResponseSerializer(serializers.ModelSerializer):
    """01. 소셜 로그인 응답의 user"""

    onboarding_completed = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'nickname', 'onboarding_completed']


class MeResponseSerializer(UserResponseSerializer):
    """04. 내 정보, 05. 닉네임 저장·온보딩 완료 처리 응답"""

    class Meta(UserResponseSerializer.Meta):
        fields = UserResponseSerializer.Meta.fields + ['created_at']
