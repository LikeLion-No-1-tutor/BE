from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()

VERIFY = 'google.oauth2.id_token.verify_oauth2_token'


class GoogleLoginViewTests(APITestCase):
    def setUp(self):
        self.url = reverse('google-login')
        self.valid_id_token = 'valid_fake_google_id_token'

        # 구글 검증 성공 시 반환할 Mock 데이터
        self.google_info = {
            'sub': 'google-123456789',
            'email': 'jimin@gmail.com',
            'email_verified': True,
        }

    def login(self, token=None):
        return self.client.post(self.url, {'id_token': token or self.valid_id_token}, format='json')

    def assert_error(self, response, http_status, code, message=None):
        self.assertEqual(response.status_code, http_status)
        error = response.json()['error']
        self.assertEqual(error['code'], code)
        if message is not None:
            self.assertEqual(error['message'], message)
        self.assertEqual(error['request_id'], response.headers['X-Request-ID'])

    # ------------------------------------------------------------------
    # 1. 성공 케이스
    # ------------------------------------------------------------------
    @patch(VERIFY)
    def test_new_user_success(self, mock_verify):
        # [성공] 최초 로그인 시 신규 유저 생성 및 토큰 발급
        mock_verify.return_value = self.google_info

        response = self.login()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('X-Request-ID', response.headers)

        data = response.json()
        self.assertTrue(data['is_new_user'])
        self.assertIn('access_token', data)
        self.assertIn('refresh_token', data)
        self.assertEqual(data['user']['email'], 'jimin@gmail.com')
        self.assertIsNone(data['user']['nickname'])
        self.assertFalse(data['user']['onboarding_completed'])

        user = User.objects.get(email='jimin@gmail.com')
        self.assertEqual(user.google_sub, 'google-123456789')
        self.assertIsNotNone(user.last_login_at)

    @patch(VERIFY)
    def test_existing_user_success(self, mock_verify):
        # [성공] 기존 유저 로그인 시 기존 정보를 반환
        mock_verify.return_value = self.google_info
        existing_user = User.objects.create_user(
            email='jimin@gmail.com',
            google_sub='google-123456789',
            nickname='지민',
        )
        existing_user.onboarding_completed_at = existing_user.created_at
        existing_user.save()

        response = self.login()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertFalse(data['is_new_user'])
        self.assertEqual(data['user']['id'], existing_user.id)
        self.assertEqual(data['user']['nickname'], '지민')
        self.assertTrue(data['user']['onboarding_completed'])

    @patch(VERIFY)
    def test_long_email_success(self, mock_verify):
        # [성공] 150자가 넘는 이메일도 가입됨 (username 길이 제한 없음)
        long_email = 'a' * 200 + '@gmail.com'
        mock_verify.return_value = {**self.google_info, 'email': long_email}

        response = self.login()

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['user']['email'], long_email)

    @patch(VERIFY)
    def test_expired_bearer_header_is_ignored(self, mock_verify):
        # [성공] 만료된 access 토큰이 헤더에 남아 있어도 로그인은 됨
        mock_verify.return_value = self.google_info
        self.client.credentials(HTTP_AUTHORIZATION='Bearer expired.or.invalid')

        response = self.login()

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    # ------------------------------------------------------------------
    # 2. 실패 / 예외 케이스
    # ------------------------------------------------------------------
    @patch(VERIFY)
    def test_same_email_different_sub_is_not_linked(self, mock_verify):
        # [실패 - 401] 같은 이메일이어도 sub가 다르면 기존 계정에 연결하지 않음
        mock_verify.return_value = {**self.google_info, 'sub': 'google-OTHER'}
        existing_user = User.objects.create_user(email='jimin@gmail.com', google_sub='google-123456789')

        response = self.login()

        self.assert_error(response, status.HTTP_401_UNAUTHORIZED, 'UNAUTHORIZED')
        self.assertNotIn('access_token', response.json())
        existing_user.refresh_from_db()
        self.assertEqual(existing_user.google_sub, 'google-123456789')
        self.assertEqual(User.objects.count(), 1)

    @patch(VERIFY)
    def test_unverified_email(self, mock_verify):
        # [실패 - 401] 구글이 이메일을 확인하지 않은 계정
        mock_verify.return_value = {**self.google_info, 'email_verified': False}

        response = self.login()

        self.assert_error(response, status.HTTP_401_UNAUTHORIZED, 'UNAUTHORIZED', '구글 로그인 정보를 확인할 수 없어요.')
        self.assertFalse(User.objects.exists())

    def test_missing_id_token(self):
        # [실패 - 400] id_token 필드가 누락되었을 때 VALIDATION_ERROR 응답
        response = self.client.post(self.url, {}, format='json')

        self.assert_error(response, status.HTTP_400_BAD_REQUEST, 'VALIDATION_ERROR', 'id_token이 필요해요.')

    def test_malformed_json(self):
        # [실패 - 400] JSON이 깨져 있어도 공통 에러 형식
        response = self.client.post(self.url, data='{not json', content_type='application/json')

        self.assert_error(response, status.HTTP_400_BAD_REQUEST, 'VALIDATION_ERROR')

    @patch(VERIFY)
    def test_invalid_id_token(self, mock_verify):
        # [실패 - 401] 유효하지 않거나 만료된 id_token 전송 시 UNAUTHORIZED 응답
        mock_verify.side_effect = ValueError('Invalid token')

        response = self.login('invalid_token')

        self.assert_error(response, status.HTTP_401_UNAUTHORIZED, 'UNAUTHORIZED', '구글 로그인 정보를 확인할 수 없어요.')

    def test_method_not_allowed(self):
        # [실패 - 405] 공통 에러 형식
        response = self.client.get(self.url)

        self.assert_error(response, status.HTTP_405_METHOD_NOT_ALLOWED, 'METHOD_NOT_ALLOWED')


class CommonRulesTests(APITestCase):
    """공통 규칙: 기본 인증 필요, 에러 형식, X-Request-ID"""

    def test_request_ids_are_unique_per_request(self):
        first = self.client.post(reverse('google-login'), {}, format='json')
        second = self.client.post(reverse('google-login'), {}, format='json')

        self.assertNotEqual(first.headers['X-Request-ID'], second.headers['X-Request-ID'])

    @override_settings(DEBUG=False)
    def test_unknown_url_returns_json_404(self):
        response = self.client.get('/api/does-not-exist')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        error = response.json()['error']
        self.assertEqual(error['code'], 'NOT_FOUND')
        self.assertEqual(error['request_id'], response.headers['X-Request-ID'])

    def test_default_permission_requires_login(self):
        from rest_framework.views import APIView
        from rest_framework.response import Response
        from rest_framework.test import APIRequestFactory

        class ProtectedView(APIView):
            def get(self, request):
                return Response({'ok': True})

        request = APIRequestFactory().get('/protected')
        request.request_id = 'test-request-id'
        response = ProtectedView.as_view()(request)

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(
            response.data,
            {'error': {'code': 'UNAUTHORIZED', 'message': '로그인이 필요해요.', 'request_id': 'test-request-id'}},
        )


class UserModelTests(APITestCase):
    def test_users_table_matches_erd(self):
        # ERD의 users 컬럼만 있어야 함 (password, last_login, is_staff 등 없음)
        columns = {field.column for field in User._meta.concrete_fields}

        self.assertEqual(User._meta.db_table, 'users')
        self.assertEqual(
            columns,
            {'id', 'email', 'google_sub', 'nickname', 'onboarding_completed_at', 'created_at', 'last_login_at'},
        )

    def test_admin_url_is_gone(self):
        response = self.client.get('/admin/')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
