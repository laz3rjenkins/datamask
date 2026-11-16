"""CLI на том же ядре:
datamask mask input.xlsx --config cfg.json --out out.xlsx --mapping out.dmmap
datamask unmask dashboard.html --mapping out.dmmap --out dashboard_real.html

Пароль — из DATAMASK_PASSWORD или интерактивно, никогда не аргументом командной строки
(аргументы видны в списке процессов и в истории оболочки)."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import secrets
import sys
import time
from pathlib import Path

from pydantic import ValidationError

from datamask.core.models import MaskConfig, UserError
from datamask.core.pipeline import run_mask
from datamask.formats import adapter_for
from datamask.formats.base import OpenOptions
from datamask.mapping.crypto import MIN_PASSWORD, write_atomic
from datamask.mapping.store import MappingStore
from datamask.report import build_report
from datamask.unmasking import unmask_file


def _password(confirm: bool = True) -> str:
    env = os.environ.get("DATAMASK_PASSWORD")
    if env is not None:
        return env
    first = getpass.getpass("Пароль таблицы соответствий: ")
    if not confirm:
        return first
    if getpass.getpass("Повторите пароль: ") != first:
        raise UserError("Пароли не совпадают")
    return first


def mask_main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="datamask mask", description="Замаскировать XLSX/CSV")
    p.add_argument("input", type=Path)
    p.add_argument("--config", type=Path, required=True, help="JSON в формате MaskConfig")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--mapping", type=Path, help="куда сохранить таблицу соответствий (.dmmap)")
    p.add_argument("--report", type=Path, help="куда сохранить отчёт (.json)")
    args = p.parse_args(argv)
    try:
        try:
            config = MaskConfig.model_validate_json(args.config.read_text(encoding="utf-8"))
        except ValidationError as e:
            fields = sorted({".".join(map(str, err["loc"])) for err in e.errors()})
            raise UserError("Неверная конфигурация: " + ", ".join(fields)) from None
        if args.out.resolve() == args.input.resolve():
            raise UserError("Исходный файл не изменяется: укажите другой --out")
        if config.save_mapping and not args.mapping:
            raise UserError('Укажите --mapping или "save_mapping": false в конфигурации')
        password = _password() if config.save_mapping else ""
        if config.save_mapping and len(password) < MIN_PASSWORD:
            raise UserError(f"Пароль — не короче {MIN_PASSWORD} символов")

        started = time.monotonic()
        adapter = adapter_for(args.input.name)
        doc = adapter.open(args.input, OpenOptions())
        store = MappingStore(secrets.token_bytes(32))
        result = run_mask(
            adapter,
            doc,
            config,
            store,
            args.out,
            lambda n: print(f"\r{n}%", end="", file=sys.stderr),
        )
        if config.save_mapping:
            write_atomic(args.mapping, store.encrypt(password))
        print("\r100%", file=sys.stderr)
        report = build_report(
            "cli", args.input.suffix.lstrip("."), config, result, config.save_mapping,
            time.monotonic() - started,
        )  # fmt: skip
        if args.report:
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
        for w in result.warnings:
            print(f"! {w}", file=sys.stderr)
        replaced = sum(c.replaced for c in result.columns)
        print(f"Готово: заменено значений {replaced}, файл {args.out.name}", file=sys.stderr)
        return 0
    except UserError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2


def unmask_main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        prog="datamask unmask",
        description="Вернуть настоящие значения: XLSX, CSV, TXT, MD, HTML, JSON",
    )
    p.add_argument("input", type=Path)
    p.add_argument("--mapping", type=Path, required=True, help="таблица соответствий (.dmmap)")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--report", type=Path, help="куда сохранить отчёт (.json)")
    args = p.parse_args(argv)
    try:
        if args.out.resolve() == args.input.resolve():
            raise UserError("Исходный файл не изменяется: укажите другой --out")
        store = MappingStore.decrypt(args.mapping.read_bytes(), _password(confirm=False))
        report = unmask_file(args.input, args.out, store)
        if args.report:
            args.report.write_text(json.dumps(report, ensure_ascii=False, indent=1), "utf-8")
        for note in report["notes"]:
            print(f"! {note}", file=sys.stderr)
        print(
            f"Готово: заменено токенов {report['tokens_replaced']}, "
            f"фейков {report['fakes_replaced']}, неизвестных токенов {report['unknown_tokens']}, "
            f"файл {args.out.name}",
            file=sys.stderr,
        )
        return 0
    except UserError as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        return 2
