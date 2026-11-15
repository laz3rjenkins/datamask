import json

from mask_helpers import CLIENTS_CONFIG
from openpyxl import load_workbook

from datamask.cli import mask_main
from datamask.mapping.store import MappingStore


def test_cli_mask(fixtures, tmp_path, monkeypatch, capsys) -> None:
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps(CLIENTS_CONFIG, ensure_ascii=False), "utf-8")
    out, mapping, report = tmp_path / "out.xlsx", tmp_path / "out.dmmap", tmp_path / "r.json"
    monkeypatch.setenv("DATAMASK_PASSWORD", "пароль-из-окружения")
    code = mask_main(
        [str(fixtures / "clients.xlsx"), "--config", str(cfg), "--out", str(out),
         "--mapping", str(mapping), "--report", str(report)]
    )  # fmt: skip
    assert code == 0, capsys.readouterr().err
    assert load_workbook(out)["Клиенты"]["B4"].value == "Клиент_0001"
    assert MappingStore.decrypt(mapping.read_bytes(), "пароль-из-окружения").entries
    assert json.loads(report.read_text("utf-8"))["file_id"] == "cli"


def test_cli_errors(fixtures, tmp_path, monkeypatch, capsys) -> None:
    src = fixtures / "clients.xlsx"
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps(CLIENTS_CONFIG, ensure_ascii=False), "utf-8")
    monkeypatch.setenv("DATAMASK_PASSWORD", "пароль-из-окружения")
    assert mask_main([str(src), "--config", str(cfg), "--out", str(src)]) == 2
    assert "Исходный файл не изменяется" in capsys.readouterr().err
    assert mask_main([str(src), "--config", str(cfg), "--out", str(tmp_path / "o.xlsx")]) == 2
    assert "--mapping" in capsys.readouterr().err
    monkeypatch.setenv("DATAMASK_PASSWORD", "short")
    args = [
        str(src),
        "--config",
        str(cfg),
        "--out",
        str(tmp_path / "o.xlsx"),
        "--mapping",
        str(tmp_path / "m"),
    ]
    assert mask_main(args) == 2
    assert "не короче" in capsys.readouterr().err
    cfg.write_text('{"sheets": {"Клиенты": {"header_row": 0}}}', "utf-8")
    assert mask_main(args) == 2
    assert "Неверная конфигурация" in capsys.readouterr().err


def test_cli_unmask(fixtures, tmp_path, monkeypatch, capsys) -> None:
    from datamask.cli import unmask_main

    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps(CLIENTS_CONFIG, ensure_ascii=False), "utf-8")
    out, mapping = tmp_path / "out.xlsx", tmp_path / "out.dmmap"
    monkeypatch.setenv("DATAMASK_PASSWORD", "пароль-из-окружения")
    mask_main([str(fixtures / "clients.xlsx"), "--config", str(cfg), "--out", str(out),
               "--mapping", str(mapping)])  # fmt: skip
    html = tmp_path / "dash.html"
    html.write_text("<td>Клиент_0001</td><td>Персона_9999</td>", "utf-8")
    restored = tmp_path / "real.html"
    assert unmask_main([str(html), "--mapping", str(mapping), "--out", str(restored)]) == 0
    original = load_workbook(fixtures / "clients.xlsx")["Клиенты"]["B4"].value
    assert restored.read_text("utf-8") == f"<td>{original}</td><td>Персона_9999</td>"
    assert "неизвестных токенов 1" in capsys.readouterr().err

    monkeypatch.setenv("DATAMASK_PASSWORD", "неверный-пароль")
    assert unmask_main([str(html), "--mapping", str(mapping), "--out", str(restored)]) == 2
    assert "Неверный пароль" in capsys.readouterr().err
