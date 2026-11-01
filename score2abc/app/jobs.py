"""A small in-memory job queue: one OMR run at a time, results kept for an hour."""
from __future__ import annotations

import os
import queue
import shutil
import tempfile
import threading
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import omr
from .mxl2abc import convert

WORKERS = int(os.environ.get("OMR_WORKERS", "1"))
MAX_QUEUE = int(os.environ.get("MAX_QUEUE", "20"))
MAX_PER_CLIENT = int(os.environ.get("MAX_JOBS_PER_CLIENT", "2"))
TTL = int(os.environ.get("JOB_TTL", "3600"))
ROOT = Path(os.environ.get("JOB_DIR", tempfile.gettempdir())) / "score2abc-jobs"


@dataclass
class Job:
    id: str
    client: str
    workdir: Path
    files: list
    status: str = "queued"          # queued | running | done | error
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    abc: str | None = None
    error: str | None = None
    log: str = ""
    musicxml: list = field(default_factory=list)

    def public(self, position: int | None) -> dict:
        now = time.time()
        return {
            "id": self.id,
            "status": self.status,
            "position": position,
            "elapsed": round((self.finished or now) - (self.started or self.created), 1),
            "abc": self.abc,
            "error": self.error,
            "log": self.log[-4000:] if self.status == "error" else None,
            "musicxml": [p.name for p in self.musicxml],
        }


class JobQueue:
    def __init__(self):
        self.jobs: dict[str, Job] = {}
        self.pending: list[str] = []
        self.q: queue.Queue = queue.Queue()
        self.lock = threading.Lock()
        ROOT.mkdir(parents=True, exist_ok=True)
        for _ in range(WORKERS):
            threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=self._janitor, daemon=True).start()

    # -------------------------------------------------------------- api
    def new_workdir(self) -> tuple[str, Path]:
        job_id = uuid.uuid4().hex
        wd = ROOT / job_id
        (wd / "in").mkdir(parents=True)
        return job_id, wd

    def submit(self, job_id: str, workdir: Path, files: list[Path], client: str) -> Job:
        with self.lock:
            if len(self.pending) >= MAX_QUEUE:
                raise RuntimeError("The server is busy. Please try again in a few minutes.")
            active = sum(1 for j in self.jobs.values()
                         if j.client == client and j.status in ("queued", "running"))
            if active >= MAX_PER_CLIENT:
                raise RuntimeError("You already have conversions in progress. Please wait for them to finish.")
            job = Job(job_id, client, workdir, files)
            self.jobs[job_id] = job
            self.pending.append(job_id)
        self.q.put(job_id)
        return job

    def get(self, job_id: str) -> tuple[Job | None, int | None]:
        with self.lock:
            job = self.jobs.get(job_id)
            pos = self.pending.index(job_id) + 1 if job_id in self.pending else None
        return job, pos

    # -------------------------------------------------------------- internals
    def _worker(self):
        while True:
            job_id = self.q.get()
            with self.lock:
                job = self.jobs.get(job_id)
                if job_id in self.pending:
                    self.pending.remove(job_id)
            if job is None:
                continue
            job.status = "running"
            job.started = time.time()
            try:
                source = omr.prepare_input(job.files, job.workdir)
                mxls, job.log = omr.run_audiveris(source, job.workdir / "out")
                job.musicxml = mxls
                tunes = []
                for n, mxl in enumerate(mxls, 1):
                    abc = convert(str(mxl))
                    tunes.append(abc.replace("X:1\n", f"X:{n}\n", 1))
                job.abc = "\n".join(tunes)
                job.status = "done"
            except omr.OmrError as exc:
                job.status, job.error = "error", str(exc)
                job.log = exc.log or job.log
            except Exception as exc:  # noqa: BLE001 - surface any failure to the user
                job.status, job.error = "error", f"Conversion failed: {exc}"
                job.log += "\n" + traceback.format_exc()
            finally:
                job.finished = time.time()

    def _janitor(self):
        while True:
            time.sleep(300)
            cutoff = time.time() - TTL
            with self.lock:
                old = [j for j in self.jobs.values()
                       if j.status in ("done", "error") and (j.finished or 0) < cutoff]
                for j in old:
                    del self.jobs[j.id]
            for j in old:
                shutil.rmtree(j.workdir, ignore_errors=True)
