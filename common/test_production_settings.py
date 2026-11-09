"""운영(DEBUG=False) 설정과 앱 로그 출력.

설정은 프로세스가 시작될 때 읽히므로 새 프로세스로 확인합니다.
"""
import json
import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase

READ_SETTINGS = """
import json
from django.conf import settings
from django.test import RequestFactory
request = RequestFactory().get('/api/personas', HTTP_X_FORWARDED_PROTO='https')
print(json.dumps({
    'is_secure': request.is_secure(),
    'session_cookie_secure': settings.SESSION_COOKIE_SECURE,
    'csrf_cookie_secure': settings.CSRF_COOKIE_SECURE,
}))
"""


def run_shell(code, debug):
    env = {**os.environ, 'GOOGLE_CLIENT_ID': 'test-client', 'DEBUG': debug}
    return subprocess.run(
        [sys.executable, 'manage.py', 'shell', '-v0', '-c', code],
        cwd=settings.BASE_DIR, env=env, capture_output=True, text=True, timeout=60,
    )


class ProductionSettingsTests(SimpleTestCase):
    def read(self, debug):
        result = run_shell(READ_SETTINGS, debug)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1])

    def test_production_trusts_proxy_and_uses_secure_cookies(self):
        self.assertEqual(self.read('False'), {
            'is_secure': True, 'session_cookie_secure': True, 'csrf_cookie_secure': True,
        })

    def test_local_development_is_unchanged(self):
        self.assertEqual(self.read('True'), {
            'is_secure': False, 'session_cookie_secure': False, 'csrf_cookie_secure': False,
        })


class AppLoggingTests(SimpleTestCase):
    def test_info_logs_of_every_app_reach_stdout(self):
        names = ['common.jobs', 'materials.tasks', 'lessons.finish', 'exams.retest']
        code = 'import logging\n' + ''.join(f"logging.getLogger('{n}').info('line from {n}')\n" for n in names)
        result = run_shell(code, 'False')
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in names:
            with self.subTest(logger=name):
                self.assertIn(f'line from {name}', result.stdout)
