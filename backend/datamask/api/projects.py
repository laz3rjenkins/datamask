"""Проекты и шаблоны настроек (экраны 1, 2, 6)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from pydantic import BaseModel

from datamask.api.errors import ApiError
from datamask.core.models import ENTITY_LABELS
from datamask.core.pipeline import ConfigError, check_params
from datamask.mapping.projects import ProjectError, ProjectMeta, ProjectRepo
from datamask.maskers import METHOD_LABELS, supported
from datamask.templates import Template, TemplateIn, TemplateRepo

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


class ProjectIn(BaseModel):
    name: str
    password: str  # нигде не сохраняется и не пишется в лог


def repo(request: Request) -> ProjectRepo:
    projects: ProjectRepo = request.app.state.projects
    return projects


def project_meta(request: Request, project_id: str) -> ProjectMeta:
    try:
        return repo(request).get(project_id)
    except ProjectError as e:
        raise ApiError(404, "project_not_found", str(e)) from e


@router.get("/projects")
def list_projects(request: Request) -> list[ProjectMeta]:
    return repo(request).all()


@router.post("/projects")
def create_project(request: Request, body: ProjectIn) -> ProjectMeta:
    try:
        meta = repo(request).create(body.name, body.password)
    except ProjectError as e:
        raise ApiError(422, "invalid_project", str(e)) from e
    logger.info("Создан проект %s", meta.id)
    return meta


@router.delete("/projects/{project_id}")
def delete_project(request: Request, project_id: str) -> dict[str, str]:
    project_meta(request, project_id)
    repo(request).delete(project_id)
    logger.info("Удалён проект %s", project_id)
    return {"status": "deleted"}


def _templates(request: Request) -> TemplateRepo:
    templates: TemplateRepo = request.app.state.templates
    return templates


@router.get("/templates")
def list_templates(request: Request) -> list[Template]:
    return _templates(request).all()


@router.post("/templates")
def create_template(request: Request, body: TemplateIn) -> Template:
    for i, rule in enumerate(body.rules, start=1):
        where = f"Правило {i}"
        if not supported(rule.entity, rule.method):
            method = METHOD_LABELS.get(rule.method, rule.method)
            raise ApiError(
                422,
                "invalid_template",
                f"{where}: способ «{method}» не подходит для типа «{ENTITY_LABELS[rule.entity]}»",
            )
        try:
            check_params(rule, where)
        except ConfigError as e:
            raise ApiError(422, "invalid_template", str(e)) from e
    return _templates(request).add(body)


@router.delete("/templates/{template_id}")
def delete_template(request: Request, template_id: str) -> dict[str, str]:
    if not _templates(request).delete(template_id):
        raise ApiError(404, "template_not_found", "Шаблон не найден")
    return {"status": "deleted"}
