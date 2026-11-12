import importlib

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Persona

User = get_user_model()


class PersonaListTests(APITestCase):
    """07. 페르소나 목록"""

    def setUp(self):
        self.url = reverse('persona-list')

    def login(self, nickname='지민'):
        user = User.objects.create_user(email='jimin@gmail.com', google_sub='sub-jimin', nickname=nickname)
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {RefreshToken.for_user(user).access_token}')

    def test_success_returns_seeded_personas_in_order(self):
        self.login()

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        items = response.json()['items']
        self.assertEqual([p['code'] for p in items], ['haneul', 'minjun', 'seoyeon', 'hyunwoo'])
        self.assertEqual([p['name'] for p in items], ['하늘', '민준', '서연', '정현우 교수님'])
        self.assertEqual([p['grade_label'] for p in items], ['초5', '고1', '대2', '교수'])
        self.assertEqual(items[3]['description'], '부드럽게 묻지만, 정의·근거·조건을 끝까지 확인해요.')
        for persona in items:
            self.assertEqual(set(persona), {'id', 'code', 'name', 'grade_label', 'description'})
            self.assertNotIn('system_prompt', persona)

    def test_nickname_required(self):
        self.login(nickname=None)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.json()['error']['code'], 'NICKNAME_REQUIRED')

    def test_requires_login(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.json()['error']['code'], 'UNAUTHORIZED')


class PersonaSeedTests(TestCase):
    """AI 서버에서 확정한 페르소나 데이터 (personas/migrations/0003_update_personas.py)"""

    def test_prompts_match_migration_data(self):
        migration = importlib.import_module('personas.migrations.0003_update_personas')
        for data in migration.PERSONAS:
            persona = Persona.objects.get(code=data['code'])
            for field, value in data.items():
                self.assertEqual(getattr(persona, field), value, (data['code'], field))

    def test_draft_common_rules_are_gone(self):
        """공통 학생 규칙은 AI 서버가 붙이므로 Django의 프롬프트에는 없다."""
        for persona in Persona.objects.all():
            self.assertNotIn('수업 대화에서 선생님이 가르쳐 준 내용만 알고', persona.system_prompt)
            self.assertTrue(persona.system_prompt.startswith('너는 '), persona.code)
