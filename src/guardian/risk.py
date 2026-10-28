"""Deterministic risk scoring and the verification policy.

The LLM never appears in this file. Policy must be auditable and reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .models import ChangeRequest, RiskAssessment, Signal, Vendor
from .parser import normalise_phone


def _registered_contacts(v: Vendor) -> set[str]:
    out = {normalise_phone(x) for x in (v.whatsapp, v.sms) if x}
    out.add(v.approver_email.lower())
    if v.email:
        out.add(v.email.lower())
    return out


def assess(req: ChangeRequest, vendor: Vendor) -> RiskAssessment:
    signals: list[Signal] = []

    bank_changed = bool(req.new_account) and req.new_account != vendor.bank_account
    if bank_changed:
        signals.append(Signal("BANK_ACCOUNT_CHANGE", 30,
                              f"Payee account differs from the registered account on file for {vendor.name}."))

    registered = _registered_contacts(vendor)
    foreign = [c for c in req.supplied_contacts
               if (normalise_phone(c) if c[0] in "+0123456789" else c) not in registered]
    contact_changed = bool(foreign)
    if contact_changed:
        signals.append(Signal("UNREGISTERED_CONTACT_SUPPLIED", 25,
                              "Request supplies contact details that are not in the trusted record: "
                              + ", ".join(foreign)))

    both = bank_changed and contact_changed
    if both:
        signals.append(Signal("PAYMENT_AND_VERIFICATION_CONTACT_CHANGE", 25,
                              "The same message changes WHERE we pay and HOW we would verify it."))

    if req.sender_domain and req.sender_domain not in [d.lower() for d in vendor.domains]:
        signals.append(Signal("SENDER_DOMAIN_NOT_SEEN", 20,
                              f"Sender domain '{req.sender_domain}' has no history with this vendor."))

    if req.reply_to and req.reply_to != req.sender:
        signals.append(Signal("REPLY_TO_MISMATCH", 15,
                              f"Replies are redirected to {req.reply_to}."))

    failed = [k for k, v in (req.auth_results or {}).items() if str(v).upper() in ("FAIL", "SOFTFAIL")]
    if failed:
        signals.append(Signal("EMAIL_AUTH_FAILURE", 20, "Failed sender authentication: " + ", ".join(sorted(failed))))

    if req.urgency_terms:
        signals.append(Signal("PRESSURE_LANGUAGE", min(5 * len(req.urgency_terms), 15),
                              "Urgency or secrecy wording: " + ", ".join(req.urgency_terms)))

    if req.amount and vendor.typical_amount and req.amount > 3 * vendor.typical_amount:
        signals.append(Signal("AMOUNT_ANOMALY", 10,
                              f"Amount {req.amount:,.0f} is over 3x the typical {vendor.typical_amount:,.0f}."))

    score = min(sum(s.weight for s in signals), 100)
    level = "HIGH" if score >= 60 else "MEDIUM" if score >= 30 else "LOW"
    return RiskAssessment(score=score, level=level, signals=signals,
                          identity_and_contact_change=both)


@dataclass
class Plan:
    action: str                       # NO_ACTION | VERIFY
    reason: str
    channels: list[tuple[str, str]] = field(default_factory=list)   # (channel, address) from REGISTRY only
    notify_approver_now: bool = False


def plan_verification(req: ChangeRequest, vendor: Vendor, risk: RiskAssessment,
                      enabled: tuple[str, ...] = ("whatsapp", "sms", "email")) -> Plan:
    """Core rule: any change to payee bank details is verified out-of-band, whatever the score.
    Contacts come exclusively from the registry, never from the request."""
    bank_changed = any(s.code == "BANK_ACCOUNT_CHANGE" for s in risk.signals)
    if not bank_changed:
        return Plan("NO_ACTION", "No payment-destination change detected.")
    chans: list[tuple[str, str]] = []
    if vendor.whatsapp and "whatsapp" in enabled:
        chans.append(("whatsapp", vendor.whatsapp))
    if vendor.sms and "sms" in enabled:
        chans.append(("sms", vendor.sms))
    if vendor.email and "email" in enabled:
        chans.append(("email", vendor.email))
    return Plan("VERIFY",
                "Payee bank details changed; verifying through the registered contact, "
                "ignoring any contact details in the request.",
                chans, notify_approver_now=risk.level == "HIGH")
