"""Контрольные суммы российских идентификаторов (SPEC §8). На вход — строка только из цифр."""

from __future__ import annotations


def _weighted(digits: str, weights: tuple[int, ...]) -> int:
    return sum(int(d) * w for d, w in zip(digits, weights, strict=False)) % 11 % 10


def inn_org_ok(d: str) -> bool:
    return len(d) == 10 and d.isdigit() and _weighted(d, (2, 4, 10, 3, 5, 9, 4, 6, 8)) == int(d[9])


def inn_person_ok(d: str) -> bool:
    return (
        len(d) == 12
        and d.isdigit()
        and _weighted(d, (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)) == int(d[10])
        and _weighted(d, (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)) == int(d[11])
    )


def snils_ok(d: str) -> bool:
    if len(d) != 11 or not d.isdigit():
        return False
    if int(d[:9]) <= 1001998:  # номера до 001-001-998 не имеют контрольного числа: не считаем
        return False
    s = sum(int(x) * w for x, w in zip(d[:9], range(9, 0, -1), strict=True))
    if s < 100:
        check = s
    elif s in (100, 101):
        check = 0
    else:
        check = s % 101
        if check == 100:
            check = 0
    return check == int(d[9:])


def luhn_ok(d: str) -> bool:
    if not 13 <= len(d) <= 19 or not d.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(d)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def ogrn_ok(d: str) -> bool:
    if not d.isdigit():
        return False
    if len(d) == 13:
        return int(d[:12]) % 11 % 10 == int(d[12])
    if len(d) == 15:
        return int(d[:14]) % 13 % 10 == int(d[14])
    return False


def ipv4_ok(s: str) -> bool:
    parts = s.split(".")
    return len(parts) == 4 and all(
        p.isdigit() and len(p) <= 3 and int(p) <= 255 and (p == "0" or not p.startswith("0"))
        for p in parts
    )
