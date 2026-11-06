from rest_framework import serializers
from django.contrib.auth import get_user_model

User = get_user_model()

class LoginRequestSerializer(serializers.Serializer):
    id_token = serializers.CharField(required=True)

class UserResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'email', 'nickname', 'onboarding_completed']