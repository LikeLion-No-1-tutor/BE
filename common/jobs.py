"""백그라운드 작업 실행기 (Django Tasks + django-tasks-db).

할 일 목록을 DB 테이블에 넣고, API 서버와 따로 도는 worker가 꺼내서 실행합니다.
서버를 재시작해도 아직 처리하지 않은 작업은 DB에 남습니다.

    worker 실행: python manage.py db_worker

작업 함수는 모듈 최상위 함수여야 하고, 인자는 ID처럼 JSON으로 저장할 수 있는 값만 넘깁니다.
테스트에서는 TASKS를 ImmediateBackend로 바꾸면 커밋 직후 바로 실행됩니다.
"""
import logging

from django.db import transaction
from django.tasks import task
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


@task
def run_job(path, args):
    """worker가 실행하는 작업. path의 함수를 찾아 args로 부릅니다."""
    func = import_string(path)
    try:
        func(*args)
    except Exception:
        # 작업 함수가 실패를 직접 기록하므로, 여기까지 온 것은 예상하지 못한 예외
        logger.exception('background job crashed', extra={'event': 'exception', 'job': func.__name__})
        raise


def enqueue(func, *args):
    """현재 트랜잭션이 커밋된 뒤 func(*args)를 백그라운드 작업으로 등록합니다."""
    path = f'{func.__module__}.{func.__qualname__}'
    transaction.on_commit(lambda: run_job.enqueue(path, list(args)))
