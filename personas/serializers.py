from rest_framework import serializers

from .models import Persona


class PersonaSerializer(serializers.ModelSerializer):
    """07. 페르소나 목록. system_prompt는 내려주지 않습니다."""

    class Meta:
        model = Persona
        fields = ['id', 'code', 'name', 'grade_label', 'description']
