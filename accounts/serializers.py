from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()


class GoogleLoginRequestSerializer(serializers.Serializer):
    id_token = serializers.CharField(required=True)


class UserResponseSerializer(serializers.ModelSerializer):
    onboarding_completed = serializers.BooleanField(read_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'nickname', 'onboarding_completed']
