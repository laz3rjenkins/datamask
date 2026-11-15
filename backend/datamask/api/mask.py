"""«До/после», запуск маскирования, задачи и скачивание результатов."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import PurePath, PureWindowsPath

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from datamask.api.errors import ApiError
from datamask.api.files import FileEntry, _entry
from datamask.core.models import MaskConfig, UserError
from datamask.core.pipeline import ConfigError, DryRun, dry_run, run_mask, validate_config
from datamask.core.session import Job, Session
from datamask.formats.base import OpenOptions
from datamask.formats.csv import CsvDocument
from datamask.mapping.crypto import MIN_PASSWORD, write_atomic
from datamask.mapping.store import MappingStore
from datamask.report import build_report, render_html

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

KINDS = {
    "masked": None,
    "mapping": "application/octet-stream",
    "report_json": "application/json",
    "report_html": "text/html; charset=utf-8",
}


class MaskIn(BaseModel):
    config: MaskConfig
    password: str | None = None  # нигде не сохраняется и не пишется в лог
    output_name: str | None = None


@dataclass
class JobOut:
    job_id: str
    status: str
    progress: int
    artifacts: list[str]
    error: str | None
    summary: dict[str, object] | None


def _validate(request: Request, file_id: str, config: MaskConfig) -> FileEntry:
    entry = _entry(request, file_id)
    try:
        validate_config(config, entry.adapter, entry.doc)
    except ConfigError as e:
        raise ApiError(422, "invalid_config", str(e)) from e
    return entry


@router.post("/files/{file_id}/dry-run")
def dry_run_endpoint(request: Request, file_id: str, config: MaskConfig) -> DryRun:
    entry = _validate(request, file_id, config)
    try:
        return dry_run(entry.adapter, entry.doc, config, entry.secret)
    except UserError as e:
        raise ApiError(400, "unreadable_file", str(e)) from e


@router.post("/files/{file_id}/mask")
def mask(request: Request, file_id: str, body: MaskIn) -> dict[str, str]:
    entry = _validate(request, file_id, body.config)
    config, password = body.config, body.password
    if config.save_mapping and (not password or len(password) < MIN_PASSWORD):
        raise ApiError(
            422, "weak_password", f"Пароль таблицы соответствий — не короче {MIN_PASSWORD} символов"
        )
    suffix = entry.path.suffix
    out_name = PureWindowsPath(body.output_name or "").name.strip() or (
        PurePath(entry.original_name).stem + "_masked" + suffix
    )
    if not out_name.lower().endswith(suffix):
        out_name += suffix
    stem = out_name[: -len(suffix)]
    options = OpenOptions(writable=True)
    if isinstance(entry.doc, CsvDocument):
        options = OpenOptions(entry.doc.encoding, entry.doc.delimiter, writable=True)

    def work(job: Job) -> None:
        started = time.monotonic()
        doc = entry.adapter.open(entry.path, options)
        store = MappingStore(entry.secret)
        result = run_mask(entry.adapter, doc, config, store, lambda p: setattr(job, "progress", p))
        masked = job.folder / f"masked{suffix}"
        entry.adapter.save(doc, masked)
        job.progress = 90
        job.artifacts["masked"] = masked
        job.download_names["masked"] = out_name
        if config.save_mapping:
            assert password is not None
            path = job.folder / "mapping.dmmap"
            write_atomic(path, store.encrypt(password))
            job.artifacts["mapping"] = path
            job.download_names["mapping"] = f"{stem}.dmmap"
        report = build_report(
            entry.id,
            suffix.lstrip("."),
            config,
            result,
            config.save_mapping,
            time.monotonic() - started,
        )
        for kind, name, data in (
            ("report_json", "report.json", json.dumps(report, ensure_ascii=False, indent=1)),
            ("report_html", "report.html", render_html(report)),
        ):
            (job.folder / name).write_text(data, encoding="utf-8")
            job.artifacts[kind] = job.folder / name
            job.download_names[kind] = f"{stem}_report{PurePath(name).suffix}"
        job.summary = {k: report[k] for k in ("by_entity", "outside_selected", "warnings")}

    session: Session = request.app.state.session
    job = session.start_job(work)
    logger.info("Маскирование %s: задача %s", file_id, job.id)
    return {"job_id": job.id}


def _job(request: Request, job_id: str) -> Job:
    job: Job | None = request.app.state.session.jobs.get(job_id)
    if job is None:
        raise ApiError(404, "job_not_found", "Задача не найдена. Возможно, сессия была очищена")
    return job


@router.get("/jobs/{job_id}")
def job_status(request: Request, job_id: str) -> JobOut:
    job = _job(request, job_id)
    return JobOut(job.id, job.status, job.progress, list(job.artifacts), job.error, job.summary)


@router.get("/jobs/{job_id}/download/{kind}")
def download(request: Request, job_id: str, kind: str) -> FileResponse:
    job = _job(request, job_id)
    if kind not in KINDS or kind not in job.artifacts or job.status != "done":
        raise ApiError(404, "artifact_not_found", "Файл ещё не готов или не создавался")
    return FileResponse(
        job.artifacts[kind], media_type=KINDS[kind], filename=job.download_names[kind]
    )
