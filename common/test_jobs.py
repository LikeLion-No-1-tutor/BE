"""백그라운드 작업 등록 (common/jobs.py)"""
from unittest.mock import patch

from django.test import TestCase, override_settings
from django_tasks_db.models import DBTaskResult

from common import jobs
from materials.tests import IMMEDIATE_TASKS

CALLS = []


def record_job(*args):
    CALLS.append(args)


def crashing_job(*args):
    raise RuntimeError('버그')


class EnqueueToDatabaseTests(TestCase):
    def test_job_is_saved_after_commit(self):
        with self.captureOnCommitCallbacks(execute=False) as callbacks:
            jobs.enqueue(record_job, 12, 'rid-1')

        self.assertEqual(len(callbacks), 1)
        self.assertFalse(DBTaskResult.objects.exists())  # 커밋 전에는 등록되지 않음

        callbacks[0]()

        job = DBTaskResult.objects.get()
        self.assertEqual(job.task_path, 'common.jobs.run_job')
        self.assertEqual(job.args_kwargs['args'], ['common.test_jobs.record_job', [12, 'rid-1']])
        self.assertEqual(job.status, 'READY')

    def test_job_does_not_run_in_the_request(self):
        CALLS.clear()
        with self.captureOnCommitCallbacks(execute=True):
            jobs.enqueue(record_job, 1)
        self.assertEqual(CALLS, [])


@override_settings(TASKS=IMMEDIATE_TASKS)
class RunJobTests(TestCase):
    def test_runs_with_the_saved_arguments(self):
        CALLS.clear()
        with self.captureOnCommitCallbacks(execute=True):
            jobs.enqueue(record_job, 12, 'rid-1')
        self.assertEqual(CALLS, [(12, 'rid-1')])

    def test_crash_is_logged(self):
        with self.assertLogs('common.jobs', level='ERROR') as logs, \
                patch('django.tasks.signals.logger'), self.captureOnCommitCallbacks(execute=True):
            jobs.enqueue(crashing_job, 1)
        self.assertEqual(logs.records[0].event, 'exception')
        self.assertEqual(logs.records[0].job, 'crashing_job')
