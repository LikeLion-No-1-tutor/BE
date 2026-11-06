from unittest.mock import patch
from django.urls import reverse
from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase
from rest_framework import status

User = get_user_model()

class GoogleLoginViewTests(APITestCase):
    def setUp(self):
        self.url = reverse('google-login')
        self.valid_id_token = "valid_fake_google_id_token"

        # 구글 검증 성공 시 반환할 Mock 데이터
        self.mock_google_user_info = {
            'sub': 'google-123456789',
            'email': 'jimin@gmail.com'
        }

    # 성공 케이스
    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_google_login_new_user_success(self, mock_verify):
        # [성공] 최초 로그인 시 신규 유저 생성 및 토큰 발급
        mock_verify.return_value = self.mock_google_user_info

        response = self.client.post(self.url, {'id_token': self.valid_id_token}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('X-Request-ID', response.headers)

        # 응답 데이터 검증
        data = response.data
        self.assertTrue(data['is_new_user'])
        self.assertIn('access_token', data)
        self.assertIn('refresh_token', data)
        self.assertEqual(data['user']['email'], 'jimin@gmail.com')
        self.assertIsNone(data['user']['nickname'])
        self.assertFalse(data['user']['onboarding_completed'])

        # DB 저장 검증
        user = User.objects.get(email='jimin@gmail.com')
        self.assertEqual(user.google_sub, 'google-123456789')

    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_google_login_existing_user_success(self, mock_verify):
        # [성공] 기존 유저 로그인 시 기존 정보를 반환
        mock_verify.return_value = self.mock_google_user_info

        # 기존 유저 미리 생성
        existing_user = User.objects.create_user(
            username='jimin@gmail.com',
            email='jimin@gmail.com',
            google_sub='google-123456789',
            nickname='지민',
            onboarding_completed=True
        )

        response = self.client.post(self.url, {'id_token': self.valid_id_token}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.data
        self.assertFalse(data['is_new_user'])
        self.assertEqual(data['user']['id'], existing_user.id)
        self.assertEqual(data['user']['nickname'], '지민')
        self.assertTrue(data['user']['onboarding_completed'])

    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_google_login_connect_existing_email(self, mock_verify):
        # [성공] google_sub는 없지만 이메일이 동일한 기존 계정에 google_sub 연동
        mock_verify.return_value = self.mock_google_user_info
        
        # google_sub가 없는 이메일 계정 미리 생성
        existing_user = User.objects.create_user(
            username='jimin@gmail.com',
            email='jimin@gmail.com'
        )
        self.assertIsNone(existing_user.google_sub)

        response = self.client.post(self.url, {'id_token': self.valid_id_token}, format='json')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data['is_new_user'])
        
        # google_sub가 업데이트되었는지 확인
        existing_user.refresh_from_db()
        self.assertEqual(existing_user.google_sub, 'google-123456789')

    # ------------------------------------------------------------------
    # 2. 실패 / 예외 케이스
    # ------------------------------------------------------------------
    def test_google_login_missing_id_token(self):
        """[실패 - 400] id_token 필드가 누락되었을 때 VALIDATION_ERROR 응답"""
        response = self.client.post(self.url, {}, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('X-Request-ID', response.headers)
        
        error = response.data['error']
        self.assertEqual(error['code'], 'VALIDATION_ERROR')
        self.assertEqual(error['message'], 'id_token이 필요해요.')
        self.assertEqual(error['request_id'], response.headers['X-Request-ID'])

    @patch('google.oauth2.id_token.verify_oauth2_token')
    def test_google_login_invalid_id_token(self, mock_verify):
        """[실패 - 401] 유효하지 않거나 만료된 id_token 전송 시 UNAUTHORIZED 응답"""
        # verify_oauth2_token 호출 시 ValueError 예외 발생시킴
        mock_verify.side_effect = ValueError("Invalid token")

        response = self.client.post(self.url, {'id_token': 'invalid_token'}, format='json')

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertIn('X-Request-ID', response.headers)

        error = response.data['error']
        self.assertEqual(error['code'], 'UNAUTHORIZED')
        self.assertEqual(error['message'], '구글 로그인 정보를 확인할 수 없어요.')
        self.assertEqual(error['request_id'], response.headers['X-Request-ID'])