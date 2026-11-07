"""02~06번 API와 NICKNAME_REQUIRED 권한 테스트"""
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, APITestCase, force_authenticate
from rest_framework.views import APIView
from rest_framework_simplejwt.token_blacklist.models import OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken

User = get_user_model()


class AuthApiTestCase(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(email='jimin@gmail.com', google_sub='sub-jimin', nickname='지민')
        self.refresh_url = reverse('token-refresh')
        self.logout_url = reverse('logout')
        self.me_url = reverse('users-me')

    def issue(self, user=None):
        """01번 로그인과 같은 방식으로 토큰 발급"""
        refresh = RefreshToken.for_user(user or self.user)
        return str(refresh.access_token), str(refresh)

    def auth(self, access):
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {access}')

    def assert_error(self, response, http_status, code, message=None):
        self.assertEqual(response.status_code, http_status)
        error = response.json()['error']
        self.assertEqual(error['code'], code)
        if message is not None:
            self.assertEqual(error['message'], message)
        self.assertEqual(error['request_id'], response.headers['X-Request-ID'])

    def refresh(self, refresh_token):
        self.client.credentials()
        return self.client.post(self.refresh_url, {'refresh_token': refresh_token}, format='json')


class TokenRefreshTests(AuthApiTestCase):
    """02. 토큰 재발급"""

    def test_success_rotates_tokens(self):
        _, refresh_token = self.issue()

        response = self.refresh(refresh_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(set(data), {'access_token', 'refresh_token'})
        self.assertNotEqual(data['refresh_token'], refresh_token)

        # 새 access 토큰으로 API를 쓸 수 있음
        self.auth(data['access_token'])
        self.assertEqual(self.client.get(self.me_url).status_code, status.HTTP_200_OK)

    def test_used_refresh_token_cannot_be_reused(self):
        _, refresh_token = self.issue()
        self.refresh(refresh_token)

        response = self.refresh(refresh_token)

        self.assert_error(response, status.HTTP_401_UNAUTHORIZED, 'UNAUTHORIZED', '다시 로그인해 주세요.')

    def test_new_refresh_token_is_recorded(self):
        # 06번 탈퇴 때 모두 블랙리스트에 넣으려면 재발급 토큰도 기록돼야 함
        _, refresh_token = self.issue()

        new_refresh = self.refresh(refresh_token).json()['refresh_token']

        jti = RefreshToken(new_refresh)['jti']
        self.assertTrue(OutstandingToken.objects.filter(jti=jti, user=self.user).exists())

    def test_missing_refresh_token(self):
        response = self.client.post(self.refresh_url, {}, format='json')

        self.assert_error(response, status.HTTP_400_BAD_REQUEST, 'VALIDATION_ERROR', 'refresh_token이 필요해요.')

    def test_invalid_refresh_token(self):
        response = self.refresh('not-a-jwt')

        self.assert_error(response, status.HTTP_401_UNAUTHORIZED, 'UNAUTHORIZED')

    def test_access_token_cannot_be_used_as_refresh(self):
        access, _ = self.issue()

        response = self.refresh(access)

        self.assert_error(response, status.HTTP_401_UNAUTHORIZED, 'UNAUTHORIZED')

    def test_works_without_nickname(self):
        user = User.objects.create_user(email='new@gmail.com', google_sub='sub-new')
        _, refresh_token = self.issue(user)

        response = self.refresh(refresh_token)

        self.assertEqual(response.status_code, status.HTTP_200_OK)


class LogoutTests(AuthApiTestCase):
    """03. 로그아웃"""

    def logout(self, access, refresh_token):
        self.auth(access)
        return self.client.post(self.logout_url, {'refresh_token': refresh_token}, format='json')

    def test_success_blacklists_refresh_token(self):
        access, refresh_token = self.issue()

        response = self.logout(access, refresh_token)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertIn('X-Request-ID', response.headers)
        self.assert_error(self.refresh(refresh_token), status.HTTP_401_UNAUTHORIZED, 'UNAUTHORIZED')

    def test_logout_twice_is_ok(self):
        access, refresh_token = self.issue()
        self.logout(access, refresh_token)

        response = self.logout(access, refresh_token)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_invalid_refresh_token_is_ok(self):
        access, _ = self.issue()

        response = self.logout(access, 'not-a-jwt')

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

    def test_other_users_token_is_not_blacklisted(self):
        other = User.objects.create_user(email='other@gmail.com', google_sub='sub-other', nickname='다른')
        _, other_refresh = self.issue(other)
        access, _ = self.issue()

        response = self.logout(access, other_refresh)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.refresh(other_refresh).status_code, status.HTTP_200_OK)

    def test_missing_refresh_token(self):
        access, _ = self.issue()
        self.auth(access)

        response = self.client.post(self.logout_url, {}, format='json')

        self.assert_error(response, status.HTTP_400_BAD_REQUEST, 'VALIDATION_ERROR', 'refresh_token이 필요해요.')

    def test_requires_access_token(self):
        _, refresh_token = self.issue()

        response = self.client.post(self.logout_url, {'refresh_token': refresh_token}, format='json')

        self.assert_error(response, status.HTTP_401_UNAUTHORIZED, 'UNAUTHORIZED', '로그인이 필요해요.')

    def test_works_without_nickname(self):
        user = User.objects.create_user(email='new@gmail.com', google_sub='sub-new')
        access, refresh_token = self.issue(user)

        response = self.logout(access, refresh_token)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)


class MeGetTests(AuthApiTestCase):
    """04. 내 정보"""

    def test_success(self):
        access, _ = self.issue()
        self.auth(access)

        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(set(data), {'id', 'email', 'nickname', 'onboarding_completed', 'created_at'})
        self.assertEqual(data['id'], self.user.id)
        self.assertEqual(data['nickname'], '지민')
        self.assertFalse(data['onboarding_completed'])
        self.assertTrue(data['created_at'].endswith('+09:00'))

    def test_works_without_nickname(self):
        user = User.objects.create_user(email='new@gmail.com', google_sub='sub-new')
        access, _ = self.issue(user)
        self.auth(access)

        response = self.client.get(self.me_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()['nickname'])

    def test_requires_login(self):
        response = self.client.get(self.me_url)

        self.assert_error(response, status.HTTP_401_UNAUTHORIZED, 'UNAUTHORIZED', '로그인이 필요해요.')

    def test_invalid_access_token(self):
        self.auth('not-a-jwt')

        response = self.client.get(self.me_url)

        self.assert_error(response, status.HTTP_401_UNAUTHORIZED, 'UNAUTHORIZED')


class MePatchTests(AuthApiTestCase):
    """05. 닉네임 저장, 온보딩 완료 처리"""

    def setUp(self):
        super().setUp()
        self.new_user = User.objects.create_user(email='new@gmail.com', google_sub='sub-new')
        access, _ = self.issue(self.new_user)
        self.auth(access)

    def patch(self, body):
        return self.client.patch(self.me_url, body, format='json')

    def test_save_nickname(self):
        response = self.patch({'nickname': '  지민  '})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['nickname'], '지민')
        self.new_user.refresh_from_db()
        self.assertEqual(self.new_user.nickname, '지민')

    def test_nickname_10_chars_ok(self):
        response = self.patch({'nickname': '가' * 10})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_invalid_nicknames(self):
        for nickname in ['', '   ', '가' * 11, 123, None]:
            with self.subTest(nickname=nickname):
                response = self.patch({'nickname': nickname})

                self.assert_error(response, status.HTTP_400_BAD_REQUEST, 'VALIDATION_ERROR', '닉네임은 1~10자여야 해요.')

        self.new_user.refresh_from_db()
        self.assertIsNone(self.new_user.nickname)

    def test_complete_onboarding_keeps_first_time(self):
        first = self.patch({'onboarding_completed': True})
        self.new_user.refresh_from_db()
        completed_at = self.new_user.onboarding_completed_at

        second = self.patch({'onboarding_completed': True})

        self.assertTrue(first.json()['onboarding_completed'])
        self.assertTrue(second.json()['onboarding_completed'])
        self.new_user.refresh_from_db()
        self.assertIsNotNone(completed_at)
        self.assertEqual(self.new_user.onboarding_completed_at, completed_at)

    def test_onboarding_only_accepts_true(self):
        for value in [False, 'true', 1, None]:
            with self.subTest(value=value):
                response = self.patch({'onboarding_completed': value})

                self.assert_error(response, status.HTTP_400_BAD_REQUEST, 'VALIDATION_ERROR')

    def test_both_fields(self):
        response = self.patch({'nickname': '지민', 'onboarding_completed': True})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()['nickname'], '지민')
        self.assertTrue(response.json()['onboarding_completed'])

    def test_no_fields(self):
        for body in [{}, {'email': 'hack@gmail.com'}]:
            with self.subTest(body=body):
                response = self.patch(body)

                self.assert_error(response, status.HTTP_400_BAD_REQUEST, 'VALIDATION_ERROR')

        self.new_user.refresh_from_db()
        self.assertEqual(self.new_user.email, 'new@gmail.com')

    def test_requires_login(self):
        self.client.credentials()

        response = self.patch({'nickname': '지민'})

        self.assert_error(response, status.HTTP_401_UNAUTHORIZED, 'UNAUTHORIZED')


class MeDeleteTests(AuthApiTestCase):
    """06. 회원 탈퇴"""

    def test_success_deletes_user_and_all_tokens(self):
        # 기기 두 대에서 로그인, 그중 하나는 재발급까지 받음
        access, refresh_a = self.issue()
        _, refresh_b = self.issue()
        rotated = self.refresh(refresh_b).json()['refresh_token']

        self.auth(access)
        response = self.client.delete(self.me_url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())

        for token in [refresh_a, rotated]:
            with self.subTest(token=token[-10:]):
                self.assert_error(self.refresh(token), status.HTTP_401_UNAUTHORIZED, 'UNAUTHORIZED')

        # 남은 access 토큰으로는 아무것도 못 함
        self.auth(access)
        self.assert_error(self.client.get(self.me_url), status.HTTP_401_UNAUTHORIZED, 'UNAUTHORIZED')

    def test_works_without_nickname(self):
        user = User.objects.create_user(email='new@gmail.com', google_sub='sub-new')
        access, _ = self.issue(user)
        self.auth(access)

        response = self.client.delete(self.me_url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(User.objects.filter(pk=user.pk).exists())

    def test_same_google_account_signs_up_again_as_new_user(self):
        access, _ = self.issue()
        self.auth(access)
        self.client.delete(self.me_url)

        again = User.objects.create_user(email='jimin@gmail.com', google_sub='sub-jimin')

        self.assertNotEqual(again.pk, self.user.pk)
        self.assertIsNone(again.nickname)

    def test_requires_login(self):
        response = self.client.delete(self.me_url)

        self.assert_error(response, status.HTTP_401_UNAUTHORIZED, 'UNAUTHORIZED')
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())


class NicknameRequiredTests(APITestCase):
    """기본 권한: 로그인 + 닉네임 (07번 이후 API)"""

    class DefaultPermissionView(APIView):
        def get(self, request):
            return Response({'ok': True})

    def call(self, user=None):
        request = APIRequestFactory().get('/api/something')
        request.request_id = 'test-request-id'
        if user is not None:
            force_authenticate(request, user=user)
        return self.DefaultPermissionView.as_view()(request)

    def test_without_nickname_returns_409(self):
        user = User.objects.create_user(email='new@gmail.com', google_sub='sub-new')

        response = self.call(user)

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(
            response.data,
            {'error': {'code': 'NICKNAME_REQUIRED', 'message': '닉네임을 먼저 저장해 주세요.', 'request_id': 'test-request-id'}},
        )

    def test_with_nickname_passes(self):
        user = User.objects.create_user(email='jimin@gmail.com', google_sub='sub-jimin', nickname='지민')

        response = self.call(user)

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_not_logged_in_is_401_not_409(self):
        response = self.call()

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data['error']['code'], 'UNAUTHORIZED')
