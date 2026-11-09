"""표준 출력에 JSON 한 줄씩 남기는 로그 형식입니다.

정해 둔 필드만 남겨서, 실수로 extra에 넣은 값이 로그에 나가지 않게 합니다.
요청 본문, 토큰, 개인 정보, 사용자가 쓴 내용은 로그에 넣지 않습니다.
"""
import contextvars
import json
import logging
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo('Asia/Seoul')

# 지금 처리 중인 요청의 ID. extra로 넘기지 않은 로그에도 붙입니다.
request_id_var = contextvars.ContextVar('request_id', default=None)

_EVENT_FIELDS = (
    'method', 'path', 'status', 'duration_ms', 'user_id', 'error_code',
    'ai_path', 'attempt', 'input_tokens', 'output_tokens',
    'job', 'target_id', 'step', 'exception_type',
)


def service_name(argv):
    """worker 프로세스와 API 서버를 로그에서 구분합니다."""
    return 'django-worker' if 'db_worker' in argv else 'django'


class JsonFormatter(logging.Formatter):
    def __init__(self, service='django', env='local'):
        super().__init__()
        self.service = service
        self.env = env

    def format(self, record):
        entry = {
            'ts': datetime.fromtimestamp(record.created, KST).isoformat(timespec='milliseconds'),
            'level': record.levelname,
            'service': self.service,
            'env': self.env,
            'request_id': getattr(record, 'request_id', None) or request_id_var.get(),
            'event': getattr(record, 'event', 'log'),
            'message': record.getMessage(),
        }
        for field in _EVENT_FIELDS:
            if hasattr(record, field):
                entry[field] = getattr(record, field)
        if record.exc_info and record.exc_info[0]:
            entry['exception_type'] = record.exc_info[0].__name__
            entry['stack_trace'] = ''.join(traceback.format_exception(*record.exc_info))
        return json.dumps(entry, ensure_ascii=False, default=str)
