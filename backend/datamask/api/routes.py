from fastapi import APIRouter, Request

from datamask import __version__
from datamask.core.session import Session

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@router.delete("/session")
def clear_session(request: Request) -> dict[str, str]:
    session: Session = request.app.state.session
    request.app.state.files.clear()
    session.clear()
    return {"status": "cleared"}
