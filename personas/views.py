from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from . import docs
from .models import Persona
from .serializers import PersonaSerializer


class PersonaListView(APIView):
    """07. 페르소나 목록 — GET /api/personas (로그인 + 닉네임 필요: 기본 권한)"""

    @docs.persona_list
    def get(self, request):
        personas = Persona.objects.order_by('display_order')
        return Response({'items': PersonaSerializer(personas, many=True).data}, status=status.HTTP_200_OK)
