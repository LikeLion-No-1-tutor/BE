"""DB 클라이언트 인증서 접속 설정 (line1_thon/db_ssl.py)."""
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from line1_thon.db_ssl import database_ssl_options


class DatabaseSslOptionsTests(SimpleTestCase):
    def test_all_paths_give_verify_identity(self):
        self.assertEqual(
            database_ssl_options('/etc/ssl/ca.crt', '/etc/django/mysql/client.crt', '/etc/django/mysql/client.key'),
            {
                'ssl_mode': 'VERIFY_IDENTITY',
                'ssl': {
                    'ca': '/etc/ssl/ca.crt',
                    'cert': '/etc/django/mysql/client.crt',
                    'key': '/etc/django/mysql/client.key',
                },
            },
        )

    def test_nothing_means_no_ssl(self):
        self.assertEqual(database_ssl_options('', '', ''), {})

    def test_partial_settings_stop_the_server(self):
        for args in [('ca', '', ''), ('', 'cert', 'key'), ('ca', 'cert', '')]:
            with self.subTest(args=args), self.assertRaises(ImproperlyConfigured):
                database_ssl_options(*args)

    def test_message_names_missing_values(self):
        with self.assertRaisesMessage(ImproperlyConfigured, 'DB_SSL_KEY'):
            database_ssl_options('ca', 'cert', '')

    def test_local_settings_have_no_ssl(self):
        # 로컬 .env에는 DB_SSL_*가 없으므로 지금처럼 SSL 없이 접속
        self.assertEqual(settings.DATABASES['default']['OPTIONS'], {})
