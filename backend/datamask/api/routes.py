from typing import Any

from fastapi import APIRouter, Request

from datamask import __version__
from datamask.core.models import ENTITY_CATEGORY, ENTITY_LABELS, EntityType
from datamask.core.pipeline import FREE_TEXT_WARNING
from datamask.core.session import Session
from datamask.detectors.suggest import DEFAULT_METHOD
from datamask.mapping.crypto import MIN_PASSWORD
from datamask.maskers import MASKERS, METHOD_LABELS, supported

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.get("/meta")
def meta(request: Request) -> dict[str, Any]:
    """Справочник для интерфейса: подписи, допустимые способы, ограничения. Без данных."""
    return {
        "entities": [
            {
                "value": e.value,
                "label": ENTITY_LABELS[e],
                "category": c.value if (c := ENTITY_CATEGORY.get(e)) else None,
                "methods": [m for m in MASKERS if supported(e, m)],
                "default_method": DEFAULT_METHOD.get(e, "pseudonym"),
            }
            for e in EntityType
        ],
        "methods": [
            {"value": m.name, "label": METHOD_LABELS[m.name], "reversible": m.reversible}
            for m in MASKERS.values()
        ],
        "min_password": MIN_PASSWORD,
        "max_upload_mb": request.app.state.max_upload_bytes // 2**20,
        "free_text_warning": FREE_TEXT_WARNING,
    }


@router.delete("/session")
def clear_session(request: Request) -> dict[str, str]:
    session: Session = request.app.state.session
    request.app.state.files.clear()
    session.clear()
    return {"status": "cleared"}
