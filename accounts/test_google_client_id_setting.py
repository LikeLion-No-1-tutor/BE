"""GOOGLE_CLIENT_ID가 비어 있으면 서버가 켜지지 않아야 합니다.

설정 파일은 프로세스가 시작될 때 읽히므로, 새 프로세스로 manage.py check를 실행해 확인합니다.
"""
import os
import subprocess
import sys

from django.conf import settings
from django.test import SimpleTestCase


class GoogleClientIdSettingTests(SimpleTestCase):
    def run_check(self, value):
        env = {**os.environ, 'GOOGLE_CLIENT_ID': value}
        return subprocess.run(
            [sys.executable, 'manage.py', 'check'],
            cwd=settings.BASE_DIR, env=env, capture_output=True, text=True, timeout=60,
        )

    def test_empty_value_stops_the_server(self):
        for value in ['', '   ']:
            with self.subTest(value=value):
                result = self.run_check(value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('ImproperlyConfigured', result.stderr)
                self.assertIn('GOOGLE_CLIENT_ID', result.stderr)

    def test_real_value_starts_normally(self):
        result = self.run_check('1234-abc.apps.googleusercontent.com')
        self.assertEqual(result.returncode, 0, result.stderr)
