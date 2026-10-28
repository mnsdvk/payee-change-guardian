"""Extract the facts we need from an inbound 'we changed our bank details' email.

Everything extracted here is UNTRUSTED. The parser never decides who to contact.
"""
from __future__ import annotations

import re
import uuid
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr

from .models import ChangeRequest

IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")
ACCT_RE = re.compile(
    r"(?:account(?:\s*(?:no\.?|number|#))?|a/c|acct)\s*[:\-]?\s*([0-9][0-9 \-]{6,22}[0-9])",
    re.I,
)
PHONE_RE = re.compile(r"(?<![\w])\+?\d[\d\s\-().]{8,16}\d(?!\w)")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
AMOUNT_RE = re.compile(r"(?:USD|EUR|INR|GBP|\$|€|£|₹|Rs\.?)\s?([0-9][0-9,]*(?:\.\d{1,2})?)", re.I)
BANK_RE = re.compile(r"\bbank(?:\s*name)?\s*[:\-]\s*([A-Za-z][A-Za-z &'-]{2,40}?)(?=[.,;\n]|$)", re.I)
SPACED_IBAN_RE = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b")

URGENCY = [
    "urgent", "urgently", "immediately", "asap", "today", "right away",
    "do not delay", "time-sensitive", "before close of business", "end of day",
    "confidential", "do not call", "don't call", "cannot be reached by phone",
]


def normalise_account(value: str) -> str:
    return re.sub(r"[\s\-]", "", value).upper()


def normalise_phone(value: str) -> str:
    digits = re.sub(r"[^\d+]", "", value)
    if digits.startswith("00"):
        digits = "+" + digits[2:]
    return digits


def _body_text(msg) -> str:
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    text = part.get_content()
    if part.get_content_type() == "text/html":
        text = re.sub(r"<[^>]+>", " ", text)
    return text


def _auth_from_headers(msg) -> dict:
    """SES stamps Authentication-Results / Received-SPF on stored inbound mail."""
    out = {}
    hdr = " ".join(str(h) for h in msg.get_all("Authentication-Results", []))
    for k in ("spf", "dkim", "dmarc"):
        m = re.search(rf"\b{k}=(\w+)", hdr, re.I)
        if m:
            out[k] = m.group(1).upper()
    if "spf" not in out:
        m = re.match(r"\s*(\w+)", str(msg.get("Received-SPF", "")))
        if m:
            out["spf"] = m.group(1).upper()
    return out


def parse_inbound(raw: bytes | str, auth_results: dict | None = None,
                  case_id: str | None = None) -> ChangeRequest:
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    sender = parseaddr(str(msg.get("From", "")))[1].lower()
    reply_to = parseaddr(str(msg.get("Reply-To", "")))[1].lower() or sender
    domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
    subject = str(msg.get("Subject", ""))
    body = _body_text(msg)
    text = f"{subject}\n{body}"

    new_account = None
    from .validate import iban_valid
    cand = [normalise_account(x) for x in IBAN_RE.findall(text)]
    cand += [normalise_account(x) for x in SPACED_IBAN_RE.findall(text)]
    cand = [c for c in cand if len(c) >= 15]
    # prefer a checksum-valid IBAN; keep an invalid one so the checksum failure is surfaced later
    valid = [c for c in cand if iban_valid(c)]
    if valid or cand:
        new_account = (valid or cand)[0]
    else:
        m2 = ACCT_RE.search(text)
        if m2:
            new_account = normalise_account(m2.group(1))

    bank = None
    mb = BANK_RE.search(text)
    if mb:
        bank = mb.group(1).strip().rstrip(".")

    phones = []
    for p in PHONE_RE.findall(text):
        n = normalise_phone(p)
        # skip things that are really the account number
        if new_account and re.sub(r"\D", "", n) in new_account:
            continue
        if len(re.sub(r"\D", "", n)) >= 9 and n not in phones:
            phones.append(n)
    emails = [e.lower() for e in EMAIL_RE.findall(text) if e.lower() != sender]
    contacts = phones + [e for e in emails if e not in phones]
    if reply_to and reply_to != sender and reply_to not in contacts:
        contacts.append(reply_to)

    low = text.lower()
    urgency = [t for t in URGENCY if t in low]

    amount = None
    ma = AMOUNT_RE.search(text)
    if ma:
        amount = float(ma.group(1).replace(",", ""))

    if not auth_results:
        auth_results = _auth_from_headers(msg)

    return ChangeRequest(
        case_id=case_id or f"case-{uuid.uuid4().hex[:10]}",
        sender=sender,
        sender_domain=domain,
        reply_to=reply_to,
        subject=subject,
        body=body.strip(),
        claimed_vendor=None,
        new_account=new_account,
        new_bank=bank,
        supplied_contacts=contacts,
        urgency_terms=urgency,
        amount=amount,
        auth_results=auth_results or {},
    )
