"""Отчёт о маскировании без самих данных: типы, количества, имена колонок и листов."""

from __future__ import annotations

import html
from datetime import UTC, datetime
from typing import Any

from datamask import __version__
from datamask.core.models import ENTITY_LABELS, MaskConfig
from datamask.core.pipeline import MaskResult
from datamask.maskers import METHOD_LABELS, reversible

CSS = """
body { font: 15px/1.5 system-ui, sans-serif; max-width: 960px; margin: 2rem auto;
       padding: 0 1rem; color: #1a1a1a; }
table { border-collapse: collapse; width: 100%; }
td, th { border: 1px solid #ccc; padding: .3rem .5rem; text-align: left; }
th { background: #f2f2f2; }
.warn { background: #fff6e0; padding: .5rem 1rem; border-left: 4px solid #e0a000; }
"""


def build_report(
    file_id: str,
    fmt: str,
    config: MaskConfig,
    result: MaskResult,
    mapping_saved: bool,
    seconds: float,
) -> dict[str, Any]:
    by_entity: dict[str, dict[str, int]] = {}
    for c in result.columns:
        e = by_entity.setdefault(c.entity.value, {"replaced": 0, "unique": 0})
        e["replaced"] += c.replaced
        e["unique"] += len(c.unique)
    return {
        "tool": f"datamask {__version__}",
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "file_id": file_id,  # не имя файла: в имени бывают ПДн
        "format": fmt,
        "duration_seconds": round(seconds, 1),
        "mapping_saved": mapping_saved,
        "categories": config.categories.model_dump(),
        "custom_terms_count": len([t for t in config.custom_terms if t.strip()]),
        "columns": [
            {
                "sheet": c.sheet,
                "column": c.key,
                "header": c.header,
                "entity": c.entity.value,
                "method": c.method,
                "reversible": reversible(c.method),
                "replaced": c.replaced,
                "unique": len(c.unique),
                "skipped_formulas": c.skipped_formulas,
                "skipped_other": c.skipped_other,
            }
            for c in result.columns
        ],
        "by_entity": by_entity,
        "free_text_fragments": {e.value: n for e, n in result.text_spans.most_common()},
        "outside_selected": result.outside_selected,
        "sanitize": result.actions,
        "warnings": result.warnings,
    }


def render_html(report: dict[str, Any]) -> str:
    def esc(v: object) -> str:
        return html.escape(str(v))

    def label(entity: str) -> str:
        return esc(next((v for k, v in ENTITY_LABELS.items() if k.value == entity), entity))

    rows = "".join(
        "<tr>"
        f"<td>{esc(c['sheet'])}</td><td>{esc(c['column'])}</td><td>{esc(c['header'])}</td>"
        f"<td>{label(c['entity'])}</td><td>{esc(METHOD_LABELS.get(c['method'], c['method']))}"
        f"{'' if c['reversible'] else ' ⚠ не восстанавливается'}</td>"
        f"<td>{c['replaced']}</td><td>{c['unique']}</td>"
        f"<td>{c['skipped_formulas'] + c['skipped_other']}</td></tr>"
        for c in report["columns"]
    )
    fragments = "".join(
        f"<li>{label(e)}: {n}</li>" for e, n in report["free_text_fragments"].items()
    )
    lists = {k: "".join(f"<li>{esc(x)}</li>" for x in report[k]) for k in ("warnings", "sanitize")}
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><title>Отчёт datamask</title>
<style>{CSS}</style></head><body>
<h1>Отчёт о маскировании</h1>
<p>{esc(report["tool"])} · {esc(report["created_at"])} · файл {esc(report["file_id"])}
 ({esc(report["format"])}) · {esc(report["duration_seconds"])} с ·
 таблица соответствий {"сохранена" if report["mapping_saved"] else "не сохранялась"}</p>
<div class="warn"><ul>{lists["warnings"]}</ul></div>
<h2>Колонки</h2>
<table><tr><th>Лист</th><th>Колонка</th><th>Заголовок</th><th>Тип</th><th>Способ</th>
<th>Заменено</th><th>Уникальных</th><th>Пропущено</th></tr>{rows}</table>
<h2>Свободный текст, шапка, примечания</h2><ul>{fragments or "<li>нет находок</li>"}</ul>
<p>Найдено и заменено вне выбранных колонок: {report["outside_selected"]}</p>
<h2>Очистка файла</h2><ul>{lists["sanitize"]}</ul>
</body></html>
"""
