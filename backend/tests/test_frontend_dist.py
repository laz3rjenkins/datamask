"""A15: собранный фронтенд не ссылается на внешние адреса."""

import re
from pathlib import Path

import pytest

DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
# Не сетевые запросы: XML-пространства имён в React DOM, ссылки на документацию в ошибках React
# и в лицензионном комментарии Tailwind.
ALLOWED = re.compile(r"https?://(www\.w3\.org/|react\.dev/errors/|tailwindcss\.com\b)")


def test_dist_has_no_external_urls() -> None:
    if not (DIST / "index.html").exists():
        pytest.skip("фронтенд не собран: cd frontend && npm run build")
    found = set()
    for f in DIST.rglob("*"):
        if f.suffix in {".html", ".js", ".css", ".json", ".svg", ".map"}:
            for url in re.findall(r"https?://[^\s\"'`)]+", f.read_text(encoding="utf-8")):
                if not ALLOWED.match(url):
                    found.add(url)
    assert not found
