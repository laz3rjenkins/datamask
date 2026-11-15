"""Автоподсказка типа колонки (SPEC §8, «Алгоритм автоподсказки»)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from datamask.core.models import ENTITY_LABELS, CellValue, EntityType
from datamask.core.normalize import to_text
from datamask.detectors.base import DetectContext, Detector, find_spans
from datamask.detectors.headers import Thresholds, header_hit, thresholds

E = EntityType
DEFAULT_METHOD: dict[EntityType, str] = {E.BIRTH_DATE: "date_shift", E.AMOUNT: "scale"}


@dataclass(frozen=True)
class Suggestion:
    entity: EntityType
    confidence: float
    method: str
    reasons: list[str] = field(default_factory=list)


def suggest_column(
    header: str,
    values: Sequence[CellValue],
    detectors: Sequence[Detector],
    th: Thresholds | None = None,
) -> Suggestion | None:
    """detectors — уже отфильтрованные по включённым категориям."""
    th = th or thresholds()
    texts = [t for t in (to_text(v) for v in values if not isinstance(v, bool)) if t]
    if not texts:
        return None

    best: tuple[float, bool, Suggestion] | None = None
    for d in detectors:
        for entity in d.entities:
            hit = header_hit(header, entity)
            matched = sum(d.match_value(t) >= th.match_value_min for t in texts)
            share = matched / len(texts)
            if d.strength == "strong":
                ok = share >= th.strong_value_share or (
                    hit is not None and share >= th.strong_with_header_share
                )
            else:
                ok = hit is not None and share >= th.weak_with_header_share
            if not ok:
                continue
            confidence = share + (1 - share) * 0.5 if hit else share
            reasons = [f"заголовок «{header}»"] if hit else []
            reasons.append(
                f"{matched} из {len(texts)} значений похожи на тип «{ENTITY_LABELS[entity]}»"
            )
            s = Suggestion(
                entity, round(confidence, 2), DEFAULT_METHOD.get(entity, "pseudonym"), reasons
            )
            key = (confidence, d.strength == "strong")
            if best is None or key > best[:2]:
                best = (*key, s)
    if best:
        return best[2]

    strong = [d for d in detectors if d.strength == "strong"]
    avg_len = sum(map(len, texts)) / len(texts)
    if avg_len <= th.free_text_min_avg_len:
        return None
    ctx = DetectContext(th.keyword_window)
    found = Counter(s.entity for t in texts for s in find_spans(t, strong, ctx))
    if not found:
        return None
    kinds = ", ".join(ENTITY_LABELS[e] for e, _ in found.most_common())
    return Suggestion(
        E.FREE_TEXT,
        0.6,
        "pseudonym",
        [
            f"средняя длина значения {avg_len:.0f} символов",
            f"внутри текста найдено: {kinds} ({sum(found.values())})",
        ],
    )
