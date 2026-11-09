"""JSON 로그 형식과 요청 로그"""
import json
import logging
import os
import re
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import path
from rest_framework.test import APIClient
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .json_log import JsonFormatter, request_id_var, service_name
from .testing import client_for, make_user


class CrashView(APIView):
    authentication_classes = []
    permission_classes = []

    def get(self, request):
        raise ValueError('boom')


urlpatterns = [path('crash', CrashView.as_view())]


def record(message='hello', exc_info=None, **extra):
    item = logging.LogRecord('common.x', logging.INFO, __file__, 1, message, (), exc_info)
    item.__dict__.update(extra)
    return item


class JsonFormatterTests(SimpleTestCase):
    def format(self, *args, **kwargs):
        return json.loads(JsonFormatter(service='django-worker', env='prod').format(record(*args, **kwargs)))

    def test_common_fields(self):
        entry = self.format('시작', event='job_started', request_id='rid-1', job='lesson_finish', target_id=3)
        self.assertRegex(entry['ts'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+09:00$')
        self.assertEqual(
            {k: entry[k] for k in ('level', 'service', 'env', 'request_id', 'event', 'message', 'job', 'target_id')},
            {'level': 'INFO', 'service': 'django-worker', 'env': 'prod', 'request_id': 'rid-1',
             'event': 'job_started', 'message': '시작', 'job': 'lesson_finish', 'target_id': 3},
        )

    def test_unknown_fields_are_not_logged(self):
        entry = self.format(event='x', email='a@example.com', content='사용자가 쓴 설명', token='secret')
        for key in ('email', 'content', 'token'):
            self.assertNotIn(key, entry)

    def test_request_id_comes_from_context(self):
        token = request_id_var.set('rid-context')
        try:
            self.assertEqual(self.format()['request_id'], 'rid-context')
        finally:
            request_id_var.reset(token)

    def test_no_request_id_is_null(self):
        self.assertIsNone(self.format()['request_id'])

    def test_exception_fields(self):
        try:
            raise ValueError('boom')
        except ValueError:
            entry = self.format(exc_info=sys.exc_info(), event='exception')
        self.assertEqual(entry['exception_type'], 'ValueError')
        self.assertIn('Traceback', entry['stack_trace'])

    def test_service_name(self):
        self.assertEqual(service_name(['manage.py', 'db_worker']), 'django-worker')
        self.assertEqual(service_name(['gunicorn', 'line1_thon.wsgi:application']), 'django')


class RequestLogTests(TestCase):
    def setUp(self):
        self.user = make_user()

    def capture(self, send):
        with self.assertLogs('common', level='INFO') as logs:
            response = send()
        return response, [r for r in logs.records if getattr(r, 'event', '') == 'http_request'][-1], logs

    def test_success(self):
        response, entry, _ = self.capture(lambda: client_for(self.user).get('/api/personas?secret=1'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual((entry.levelname, entry.method, entry.path, entry.status, entry.user_id),
                         ('INFO', 'GET', '/api/personas', 200, self.user.id))
        self.assertEqual(entry.request_id, response.headers['X-Request-ID'])
        self.assertGreaterEqual(entry.duration_ms, 0)
        self.assertFalse(hasattr(entry, 'error_code'))

    def test_401_is_info(self):
        _, entry, _ = self.capture(lambda: APIClient().get('/api/users/me'))
        self.assertEqual((entry.levelname, entry.status, entry.error_code, entry.user_id),
                         ('INFO', 401, 'UNAUTHORIZED', None))

    def test_other_4xx_is_warning(self):
        _, entry, _ = self.capture(lambda: client_for(self.user).get('/api/lessons/999999'))
        self.assertEqual((entry.levelname, entry.status, entry.error_code), ('WARNING', 404, 'NOT_FOUND'))

    def test_url_not_found_is_warning(self):
        _, entry, _ = self.capture(lambda: APIClient().get('/api/no-such-path'))
        self.assertEqual((entry.levelname, entry.status, entry.error_code), ('WARNING', 404, 'NOT_FOUND'))

    @override_settings(ROOT_URLCONF='common.test_json_log')
    def test_5xx_is_error(self):
        client = APIClient(raise_request_exception=False)
        _, entry, logs = self.capture(lambda: client.get('/crash'))
        self.assertEqual((entry.levelname, entry.status, entry.error_code), ('ERROR', 500, 'INTERNAL_SERVER_ERROR'))
        crash = [r for r in logs.records if getattr(r, 'event', '') == 'exception'][0]
        self.assertEqual(crash.request_id, entry.request_id)

    def test_secrets_and_body_are_not_logged(self):
        token = str(RefreshToken.for_user(self.user).access_token)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')
        _, _, logs = self.capture(lambda: client.post('/api/lessons', {'memo': '비밀-메모'}, format='json'))
        text = '\n'.join(JsonFormatter().format(r) for r in logs.records)
        self.assertNotIn(token, text)
        self.assertNotIn('비밀-메모', text)
        self.assertNotIn(self.user.email, text)


class ProcessLogTests(SimpleTestCase):
    """로그 설정은 프로세스가 시작될 때 적용되므로 새 프로세스로 확인합니다."""

    def lines(self, **env_vars):
        code = "import logging; logging.getLogger('lessons.finish').info('hello', extra={'event': 'job_started'})"
        env = {**os.environ, 'GOOGLE_CLIENT_ID': 'test-client', **env_vars}
        result = subprocess.run(
            [sys.executable, 'manage.py', 'shell', '-v0', '-c', code],
            cwd=settings.BASE_DIR, env=env, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return [json.loads(line) for line in result.stdout.splitlines() if re.match(r'^\{', line)]

    def test_stdout_is_json_and_env_follows_debug(self):
        self.assertEqual(self.lines(DEBUG='False')[-1]['env'], 'prod')
        self.assertEqual(self.lines(DEBUG='True')[-1]['env'], 'local')

    def test_app_env_overrides(self):
        entry = self.lines(DEBUG='False', APP_ENV='staging')[-1]
        self.assertEqual((entry['env'], entry['service'], entry['event']), ('staging', 'django', 'job_started'))
