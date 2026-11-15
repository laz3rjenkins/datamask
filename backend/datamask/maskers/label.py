from __future__ import annotations

from datamask.core.models import ENTITY_LABELS, CellValue, EntityType
from datamask.maskers.base import ALL, MaskContext


class LabelMasker:
    name = "label"
    reversible = False
    supports = ALL

    def mask(self, value: CellValue, entity: EntityType, ctx: MaskContext) -> CellValue:
        return f"[{ENTITY_LABELS[entity]}]"


class DeleteMasker:
    name = "delete"
    reversible = False
    supports = ALL

    def mask(self, value: CellValue, entity: EntityType, ctx: MaskContext) -> CellValue:
        return None
