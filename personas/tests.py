from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

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
        self.assertEqual([p['code'] for p in items], ['haneul', 'minjun', 'seoyeon'])
        self.assertEqual([p['name'] for p in items], ['하늘', '민준', '서연'])
        self.assertEqual([p['grade_label'] for p in items], ['초5', '고1', '대2'])
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
