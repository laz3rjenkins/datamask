"""Размаскировка (экран 5): файл + таблица соответствий (.dmmap) или проект + пароль → задача."""

from __future__ import annotations

import logging
import secrets
import shutil
from pathlib import PurePath, PureWindowsPath

from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from datamask.api.errors import ApiError
from datamask.api.files import _save, _too_large
from datamask.api.projects import project_meta, repo
from datamask.core.session import Job, Session
from datamask.mapping.crypto import MappingError
from datamask.mapping.store import MappingStore
from datamask.unmasking import UNMASK_EXTENSIONS, unmask_file

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


@router.post("/unmask")
async def unmask(request: Request) -> dict[str, str]:
    limit: int = request.app.state.max_upload_bytes
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > 2 * limit + 64 * 1024:
        raise _too_large(limit)
    form = await request.form(max_files=2, max_fields=4)
    file, mapping = form.get("file"), form.get("mapping")
    project_id, password = form.get("project_id"), form.get("password")
    if not isinstance(file, UploadFile) or not file.filename:
        raise ApiError(400, "no_file", "Файл не передан")
    name = PureWindowsPath(file.filename).name
    suffix = PurePath(name).suffix.lower()
    if suffix not in UNMASK_EXTENSIONS:
        raise ApiError(
            415, "unsupported_format", "Размаскировать можно файлы XLSX, CSV, TXT, MD, HTML и JSON"
        )
    has_mapping = isinstance(mapping, UploadFile) and bool(mapping.filename)
    if has_mapping == bool(project_id):
        raise ApiError(400, "no_mapping", "Выберите таблицу соответствий (.dmmap) или проект")
    if not isinstance(password, str) or not password:
        raise ApiError(400, "no_password", "Введите пароль")
    if isinstance(project_id, str) and project_id:
        project_meta(request, project_id)

    session: Session = request.app.state.session
    folder = session.path / "unmask" / secrets.token_hex(8)
    folder.mkdir(parents=True)
    src = folder / f"source{suffix}"
    try:
        await run_in_threadpool(_save, file.file, src, limit)
        if isinstance(mapping, UploadFile) and has_mapping:
            await run_in_threadpool(_save, mapping.file, folder / "mapping.dmmap", limit)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    projects = repo(request)
    out_name = f"{PurePath(name).stem}_unmasked{suffix}"

    def work(job: Job) -> None:
        try:
            if isinstance(project_id, str) and project_id:
                store = projects.load(project_id, password)
            else:
                store = MappingStore.decrypt((folder / "mapping.dmmap").read_bytes(), password)
        except MappingError as e:
            raise MappingError("Неверный пароль или файл таблицы соответствий повреждён") from e
        job.progress = 20
        restored = job.folder / f"restored{suffix}"
        report = unmask_file(src, restored, store)
        job.artifacts["restored"] = restored
        job.download_names["restored"] = out_name
        job.summary = report

    job = session.start_job(work)
    logger.info("Размаскировка: задача %s", job.id)
    return {"job_id": job.id}
