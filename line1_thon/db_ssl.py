"""DB 클라이언트 인증서 접속 설정.

운영 DB(MySQL)는 비밀번호 없이 클라이언트 인증서로만 들어옵니다.
환경 변수 DB_SSL_CA, DB_SSL_CERT, DB_SSL_KEY를 모두 주면 TLS로 접속하고,
DB 서버 인증서가 우리 CA가 서명한 것인지와 접속 주소(IP)까지 확인합니다 (VERIFY_IDENTITY).
셋 다 비어 있으면 지금처럼 SSL 없이 접속합니다 (로컬 개발).
"""
from django.core.exceptions import ImproperlyConfigured


def database_ssl_options(ca, cert, key):
    """DATABASES['default']['OPTIONS']에 넣을 값. 설정하지 않았으면 빈 dict."""
    paths = {'DB_SSL_CA': ca, 'DB_SSL_CERT': cert, 'DB_SSL_KEY': key}
    given = [name for name, value in paths.items() if value]
    if not given:
        return {}
    if len(given) != len(paths):
        missing = ', '.join(name for name, value in paths.items() if not value)
        raise ImproperlyConfigured(f'DB 인증서 접속에는 DB_SSL_CA, DB_SSL_CERT, DB_SSL_KEY가 모두 필요해요. 빠진 값: {missing}')
    return {
        'ssl_mode': 'VERIFY_IDENTITY',
        'ssl': {'ca': ca, 'cert': cert, 'key': key},
    }
