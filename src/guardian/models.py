"""Plain data types shared by the core logic and the AWS layer."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Vendor:
    vendor_id: str
    name: str
    domains: list[str]            # sender domains we have seen legitimately
    whatsapp: Optional[str]       # registered E.164 number (trusted channel #1)
    sms: Optional[str]            # registered E.164 number (trusted channel #2)
    approver_email: str           # human fallback inside OUR organisation
    bank_account: str             # currently trusted payee account (normalised)
    bank_name: str = ""
    typical_amount: float = 0.0
    email: Optional[str] = None   # registered supplier contact email (trusted channel #3)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ChangeRequest:
    """What we extracted from the inbound email. Nothing here is trusted."""
    case_id: str
    sender: str
    sender_domain: str
    reply_to: str
    subject: str
    body: str
    claimed_vendor: Optional[str] = None
    new_account: Optional[str] = None
    new_bank: Optional[str] = None
    supplied_contacts: list[str] = field(default_factory=list)  # phones/emails in the request
    urgency_terms: list[str] = field(default_factory=list)
    amount: Optional[float] = None
    auth_results: dict = field(default_factory=dict)  # spf/dkim/dmarc verdicts from SES

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Signal:
    code: str
    weight: int
    detail: str


@dataclass
class RiskAssessment:
    score: int
    level: str                    # LOW | MEDIUM | HIGH
    signals: list[Signal]
    identity_and_contact_change: bool
    verification_contact_source: str = "registry"  # never "request"

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# Case lifecycle states
RECEIVED = "RECEIVED"
HELD = "HELD"                       # payment instruction frozen, awaiting verification
VERIFYING = "VERIFYING"
APPROVED = "APPROVED"
BLOCKED = "BLOCKED"
ESCALATED = "ESCALATED"
NO_VENDOR = "UNKNOWN_VENDOR"
