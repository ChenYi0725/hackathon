"""Bounded background previews keep upstream queries out of HTTP timeout windows."""
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from app.application.ports import ExtractionUnavailable, RevisionConflict


class AutofillJobs:
    def __init__(self, autofill):
        self.autofill = autofill
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='autofill')
        self.lock, self.jobs = threading.Lock(), {}

    def start(self, case_id, request):
        if self.autofill.repository.get_case(case_id).revision != request.revision:
            raise RevisionConflict('案件已更新，請重新載入。')
        with self.lock:
            if sum(j['status'] in ('queued', 'running') for j in self.jobs.values()) >= 2:
                raise ExtractionUnavailable('已有選填查詢進行中，請稍後重試。')
            for key in list(self.jobs):
                if self.jobs[key]['status'] not in ('queued', 'running') and (len(self.jobs) >= 20 or time.time()-self.jobs[key]['created_at']>1800):
                    del self.jobs[key]
            key = uuid.uuid4().hex
            self.jobs[key] = dict(id=key, case_id=case_id, status='queued', created_at=time.time(), result=None)
        self.executor.submit(self._run, key, case_id, request)
        return dict(job_id=key, status='queued')

    def _run(self, key, case_id, request):
        with self.lock:
            self.jobs[key]['status'] = 'running'
        try:
            result = self.autofill.preview(case_id, request)
            with self.lock:
                self.jobs[key].update(status='done', result=result)
        except RevisionConflict:
            with self.lock:
                self.jobs[key].update(status='stale', error='查詢期間案件已更新；請重新查詢。')
        except Exception:
            with self.lock:
                self.jobs[key].update(status='error', error='選填查詢失敗；案件未變更，請稍後重試。')

    def get(self, case_id, key):
        with self.lock:
            if key not in self.jobs or self.jobs[key]['case_id'] != case_id:
                raise KeyError(key)
            return dict(self.jobs[key])

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)
