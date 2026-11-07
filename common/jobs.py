"""백그라운드 작업 실행기.

지금은 같은 프로세스의 스레드 풀에서 돌립니다 (해커톤용, 추가 설치 없음).
서버를 재시작하면 진행 중이던 작업은 사라지고 대상은 processing 상태로 남습니다.
나중에 Celery 등으로 바꿀 때는 enqueue()만 바꾸면 됩니다. 작업 함수는 인자로 ID만 받습니다.

BACKGROUND_JOBS_SYNC=True이면 (테스트용) 스레드 없이 바로 실행합니다.
"""
import logging
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.db import close_old_connections, connections, transaction

logger = logging.getLogger(__name__)

_executor = None


def _get_executor():
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=getattr(settings, 'BACKGROUND_JOB_WORKERS', 4),
            thread_name_prefix='bg-job',
        )
    return _executor


def _run(func, args):
    close_old_connections()
    try:
        func(*args)
    except Exception:
        # 작업 함수가 실패를 직접 기록하므로, 여기까지 온 것은 예상하지 못한 예외
        logger.exception('background job crashed', extra={'event': 'exception', 'job': func.__name__})
    finally:
        connections.close_all()  # 스레드가 연 DB 연결 정리


def enqueue(func, *args):
    """현재 트랜잭션이 커밋된 뒤 func(*args)를 백그라운드에서 실행합니다."""

    def submit():
        if getattr(settings, 'BACKGROUND_JOBS_SYNC', False):
            func(*args)
        else:
            _get_executor().submit(_run, func, args)

    transaction.on_commit(submit)
