"""다른 주소에서 운영하는 프론트엔드의 브라우저 요청 허용 (CORS)"""
import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from .testing import client_for, make_user

FRONT = 'https://app.example.com'
OTHER = 'https://evil.example.com'


@override_settings(CORS_ALLOWED_ORIGINS=[FRONT])
class CorsTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def preflight(self, path, method, headers, origin=FRONT):
        return self.client.options(
            path,
            HTTP_ORIGIN=origin,
            HTTP_ACCESS_CONTROL_REQUEST_METHOD=method,
            HTTP_ACCESS_CONTROL_REQUEST_HEADERS=headers,
        )

    def test_allowed_origin(self):
        response = client_for(self.user).get('/api/personas', HTTP_ORIGIN=FRONT)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response['Access-Control-Allow-Origin'], FRONT)

    def test_other_origin_is_not_allowed(self):
        response = client_for(self.user).get('/api/personas', HTTP_ORIGIN=OTHER)
        self.assertNotIn('Access-Control-Allow-Origin', response)

    def test_preflight_for_authorized_request_needs_no_login(self):
        response = self.preflight('/api/users/me', 'PATCH', 'authorization,content-type')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Access-Control-Allow-Origin'], FRONT)
        self.assertIn('PATCH', response['Access-Control-Allow-Methods'])
        self.assertIn('DELETE', response['Access-Control-Allow-Methods'])
        self.assertIn('authorization', response['Access-Control-Allow-Headers'])

    def test_preflight_for_file_upload(self):
        response = self.preflight('/api/materials', 'POST', 'authorization')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Access-Control-Allow-Origin'], FRONT)

    def test_preflight_from_other_origin_is_not_allowed(self):
        response = self.preflight('/api/users/me', 'PATCH', 'authorization', origin=OTHER)
        self.assertNotIn('Access-Control-Allow-Origin', response)

    def test_error_response_is_readable(self):
        response = self.client.get('/api/users/me', HTTP_ORIGIN=FRONT)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response['Access-Control-Allow-Origin'], FRONT)
        self.assertEqual(response.json()['error']['code'], 'UNAUTHORIZED')

    def test_request_id_is_exposed_to_browser(self):
        response = client_for(self.user).get('/api/personas', HTTP_ORIGIN=FRONT)
        self.assertIn('X-Request-ID', response)
        self.assertIn('x-request-id', response['Access-Control-Expose-Headers'].lower())

    def test_credentials_are_not_allowed(self):
        response = client_for(self.user).get('/api/personas', HTTP_ORIGIN=FRONT)
        self.assertNotIn('Access-Control-Allow-Credentials', response)


class CorsSettingTests(SimpleTestCase):
    """설정은 프로세스가 시작될 때 읽히므로 새 프로세스로 manage.py check를 실행해 확인합니다."""

    def check(self, value):
        env = {**os.environ, 'GOOGLE_CLIENT_ID': 'test-client', 'CORS_ALLOWED_ORIGINS': value}
        return subprocess.run(
            [sys.executable, 'manage.py', 'check'],
            cwd=settings.BASE_DIR, env=env, capture_output=True, text=True,
        )

    def test_empty_value_allows_nothing_and_server_starts(self):
        self.assertEqual(self.check('').returncode, 0)

    def test_several_origins(self):
        self.assertEqual(self.check(f'{FRONT},http://localhost:3000').returncode, 0)

    def test_origin_without_scheme_stops_server(self):
        result = self.check('app.example.com')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('corsheaders.E013', result.stderr)

    def test_origin_with_path_stops_server(self):
        result = self.check(f'{FRONT}/')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('corsheaders.E014', result.stderr)
