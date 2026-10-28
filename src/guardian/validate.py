"""Secondary checks run AFTER the registered contact says yes."""
from __future__ import annotations

import re


def iban_valid(iban: str) -> bool:
    s = iban.replace(" ", "").upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{10,30}", s):
        return False
    r = s[4:] + s[:4]
    num = "".join(str(int(c, 36)) for c in r)
    return int(num) % 97 == 1


def account_format_ok(account: str) -> bool:
    if re.match(r"^[A-Z]{2}\d{2}", account):
        return iban_valid(account)
    return bool(re.fullmatch(r"\d{8,18}", account))


def mask(account: str) -> str:
    if not account:
        return "(none)"
    return "•" * max(len(account) - 4, 0) + account[-4:]


def mask_email(addr: str) -> str:
    if not addr or "@" not in addr:
        return mask(addr or "")
    user, dom = addr.split("@", 1)
    return (user[:1] + "***" if len(user) > 1 else "*") + "@" + dom
