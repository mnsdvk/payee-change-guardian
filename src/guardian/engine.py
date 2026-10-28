"""The Guardian case engine.

One implementation, driven two ways:
  * Lambda handlers + Step Functions (waitForTaskToken) on AWS
  * LocalRunner (below) for the offline end-to-end demo and tests
"""
from __future__ import annotations

import os
import secrets
import time
from typing import Callable, Optional

from . import models as M
from .channels.messenger import Messenger
from .interpret import APPROVE, DENY, Interpretation, interpret_reply
from .parser import normalise_phone, parse_inbound
from .registry import Registry, resolve_vendor
from .risk import assess, plan_verification
from .store import InMemoryCaseStore
from .validate import account_format_ok, mask, mask_email

CHANNEL_ORDER = ["whatsapp", "sms", "email"]


class Guardian:
    def __init__(self, registry: Registry, store, messenger: Messenger,
                 model: Optional[Callable[[str], dict]] = None, clock=time.time,
                 analyst: Optional[Callable[[dict, dict], Optional[dict]]] = None):
        self.registry, self.store, self.msg, self.model, self.clock = registry, store, messenger, model, clock
        self.analyst = analyst

    # ---- audit ----
    def _log(self, case: dict, kind: str, detail: str, **extra) -> None:
        case.setdefault("timeline", []).append(
            {"t": self.clock(), "type": kind, "detail": detail, **extra})

    # ---- advisory AI note: runs off the decision path, never affects routing or the outcome ----
    AI_STALE = 100          # seconds before a started-but-unfinished note is treated as dead

    def claim_ai_note(self, case_id: str, force: bool = False) -> bool:
        """Decide whether an AI note should be generated now, and mark it as started."""
        case = self.store.get(case_id)
        if not case or self.analyst is None or not case.get("risk") or case.get("ai_analysis"):
            return False
        last_skip = max([e["t"] for e in case.get("timeline", []) if e["type"] == "AI_UNAVAILABLE"] or [0])
        started = case.get("ai_started", 0)
        if started > last_skip and self.clock() - started < self.AI_STALE:
            return False                                   # a run is already in progress
        if last_skip and not force:
            return False                                   # failed earlier; only an explicit retry runs again
        case["ai_started"] = self.clock()
        self.store.put(case)
        return True

    def run_ai_note(self, case_id: str) -> Optional[dict]:
        case = self.store.get(case_id)
        if not case or self.analyst is None or not case.get("risk"):
            return case
        tmp = {"timeline": []}
        note = None
        try:
            note = self.analyst(case["request"], case["risk"])
            self._log(tmp, "AI_ANALYSIS", "AI wrote an advisory note on the request.")
        except Exception as exc:
            why = str(exc)[:200] if isinstance(exc, RuntimeError) else type(exc).__name__
            self._log(tmp, "AI_UNAVAILABLE", f"AI note skipped ({why}); decision unaffected.")
        fresh = self.store.get(case_id) or case              # keep any decision made while the model was thinking
        fresh["timeline"] = sorted(fresh.get("timeline", []) + tmp["timeline"], key=lambda e: e["t"])
        if note:
            fresh["ai_analysis"] = note
        self.store.put(fresh)
        return fresh

    def add_ai_note(self, case_id: str, force: bool = False) -> Optional[dict]:
        """Inline version (local runs and tests)."""
        if self.claim_ai_note(case_id, force):
            self.run_ai_note(case_id)
        return self.store.get(case_id)

    # ---- step 1: ingest ----
    def open_case(self, raw: bytes | str, auth_results: Optional[dict] = None,
                  case_id: Optional[str] = None) -> dict:
        req = parse_inbound(raw, auth_results, case_id)
        case: dict = {"case_id": req.case_id, "created": self.clock(), "state": M.RECEIVED,
                      "request": req.to_dict(), "timeline": []}
        self._log(case, "EMAIL_RECEIVED", f"Request from {req.sender} (reply-to {req.reply_to})")

        vendor = resolve_vendor(self.registry, req)
        if vendor is None:
            case["state"] = M.NO_VENDOR
            self._log(case, "NO_VENDOR_MATCH", "Sender does not map to any registered vendor; nothing changed.")
            self.store.put(case)
            return case
        case["vendor_id"], case["vendor_name"] = vendor.vendor_id, vendor.name

        risk = assess(req, vendor)
        enabled = tuple(x.strip() for x in os.environ.get("ENABLED_CHANNELS", "whatsapp,sms,email").split(",") if x.strip())
        plan = plan_verification(req, vendor, risk, enabled)
        case["risk"] = risk.to_dict()
        case["plan"] = {"action": plan.action, "channels": plan.channels, "reason": plan.reason}
        case["trusted"] = {
            "bank_name": vendor.bank_name,
            "account": mask(vendor.bank_account),
            "domains": list(vendor.domains),
            "channels": [{"channel": c, "to": mask_email(a) if c == "email" else mask(a)} for c, a in plan.channels],
        }
        self._log(case, "RISK_ASSESSED", f"{risk.level} ({risk.score})",
                  signals=[s.code for s in risk.signals])

        if plan.action == "NO_ACTION":
            case["state"] = M.APPROVED
            case["outcome"] = "No payment-destination change; nothing to verify."
            self._log(case, "NO_ACTION", plan.reason)
            self.store.put(case)
            return case

        case["state"] = M.HELD
        self._log(case, "PAYMENT_CHANGE_HELD",
                  "Existing payee details stay in force until the registered contact confirms.")
        if risk.identity_and_contact_change:
            self._log(case, "POLICY",
                      "Request changes both payee account and verification contact. Verification will use "
                      "ONLY contact details already in the trusted record; supplied contacts are ignored.",
                      ignored_contacts=req.supplied_contacts)
        if plan.notify_approver_now:
            self._notify_approver(case, vendor, "High-risk change held. Review is in progress.")
        self.store.put(case)
        return case

    def _notify_approver(self, case: dict, vendor: M.Vendor, headline: str) -> None:
        r = case["risk"]
        body = (f"{headline}\n\nCase: {case['case_id']}\nVendor: {vendor.name}\n"
                f"Risk: {r['level']} ({r['score']})\n"
                + "\n".join(f"- {s['code']}: {s['detail']}" for s in r["signals"]))
        try:
            mid = self.msg.send_email(vendor.approver_email,
                                      f"[Guardian] {case['case_id']} {vendor.name}", body)
            self._log(case, "APPROVER_EMAILED", f"SES message {mid}", channel="email")
        except Exception as exc:
            self._log(case, "SEND_FAILED", f"approver email: {type(exc).__name__}", channel="email")

    # ---- step 2: send verification on a channel (called per Step Functions state) ----
    def send_verification(self, case_id: str, channel: str, task_token: str = "") -> dict:
        case = self.store.get(case_id)
        vendor = self.registry.get(case["vendor_id"])
        address = dict(case["plan"]["channels"]).get(channel)   # registry-derived, never from request
        if not address:
            self._log(case, "CHANNEL_UNAVAILABLE", f"No registered {channel} contact for {vendor.name}.")
            self.store.put(case)
            return {"sent": False, "channel": channel}
        text = ("Payment-details check: we received a request to change your payee bank account from "
                f"{mask(vendor.bank_account)} to {mask(case['request']['new_account'] or '')}. "
                "Did YOUR organisation authorise this change?")
        if channel == "email":
            toks = {"yes": secrets.token_urlsafe(24), "no": secrets.token_urlsafe(24)}
            case["link_tokens"] = toks
            base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
            text = (text + f"\n\nTo answer, open ONE of these pages and press the button there:\n"
                    f"  Yes, we authorised it: {base}/v/{toks['yes']}\n"
                    f"  No, we did NOT: {base}/v/{toks['no']}\n\n"
                    "If you did not expect this message, choose No. Nobody will ever ask you to confirm by "
                    "replying with new bank or contact details.")
        try:
            mid = self.msg.send_on(channel, address, text, case_id)
        except Exception as exc:
            self._log(case, "SEND_FAILED", f"{channel}: {type(exc).__name__}: {exc}", channel=channel)
            self.store.put(case)
            return {"sent": False, "channel": channel}
        case["state"] = M.VERIFYING
        case["awaiting_phone"] = normalise_phone(address) if channel != "email" else ""
        case["awaiting_channel"] = channel
        if task_token:
            case["task_token"] = task_token
        shown = mask_email(address) if channel == "email" else mask(address)
        self._log(case, "VERIFICATION_SENT", f"{channel} to registered contact {shown}",
                  channel=channel, message_id=mid)
        self.store.put(case)
        return {"sent": True, "channel": channel}

    # ---- step 3: a reply arrives ----
    def handle_reply(self, case_id: str, text: str = "", button_id: str = "",
                     channel: str = "") -> Interpretation:
        case = self.store.get(case_id)
        interp = interpret_reply(text, button_id, self.model)
        self._log(case, "REPLY_RECEIVED", f"{interp.label} via {interp.source} ({interp.confidence:.2f})",
                  channel=channel or case.get("awaiting_channel"), note=interp.note, raw=(text or button_id)[:200])
        case["interpretation"] = {"label": interp.label, "source": interp.source,
                                  "confidence": interp.confidence, "note": interp.note}
        self.store.put(case)
        return interp

    # ---- email confirmation pages (GET only previews; POST decides) ----
    def preview_link(self, token: str) -> Optional[dict]:
        case = self.store.find_by_link_token(token)
        if not case or case.get("state") != M.VERIFYING or case.get("awaiting_channel") != "email":
            return None
        answer = "yes" if case["link_tokens"].get("yes") == token else "no"
        r = case["request"]
        return {"case_id": case["case_id"], "vendor": case.get("vendor_name"), "answer": answer,
                "new_account": mask(r.get("new_account") or "")}

    def complete_link(self, token: str):
        """Called on POST. One-time use. Returns (case, Interpretation) or None."""
        info = self.preview_link(token)
        if not info:
            return None
        case = self.store.get(info["case_id"])
        case.pop("link_tokens", None)       # burn both tokens
        self.store.put(case)
        btn = ("GUARDIAN_AUTHORIZED:" if info["answer"] == "yes" else "GUARDIAN_DENIED:") + info["case_id"]
        interp = self.handle_reply(info["case_id"], button_id=btn, channel="email")
        return self.store.get(info["case_id"]), interp

    # ---- step 4: decision ----
    def finalize(self, case_id: str, decision: str) -> dict:
        case = self.store.get(case_id)
        vendor = self.registry.get(case["vendor_id"])
        req = case["request"]
        if decision == DENY:
            case["state"] = M.BLOCKED
            case["outcome"] = "Registered contact denied the change. Payment details NOT modified."
            self._log(case, "BLOCKED", case["outcome"])
            self._notify_approver(case, vendor, "BLOCKED: the registered contact denied this change. Possible fraud.")
        elif decision == APPROVE:
            ok, why = self._secondary_checks(case, vendor, req)
            if ok:
                self.registry.update_bank(vendor.vendor_id, req["new_account"], req.get("new_bank") or "")
                case["state"] = M.APPROVED
                case["outcome"] = "Confirmed by registered contact; secondary checks passed; payee details updated."
                self._log(case, "APPROVED", case["outcome"])
            else:
                case["state"] = M.ESCALATED
                case["outcome"] = f"Contact confirmed but a secondary check failed: {why}. Held for human review."
                self._log(case, "SECONDARY_CHECK_FAILED", why)
                self._notify_approver(case, vendor, case["outcome"])
        else:  # no clean answer
            case["state"] = M.ESCALATED
            case["outcome"] = "No clean confirmation. Held for human review; payee details NOT modified."
            self._log(case, "ESCALATED", case["outcome"])
            self._notify_approver(case, vendor, case["outcome"])
        case.pop("task_token", None)
        self.store.put(case)
        return case

    def _secondary_checks(self, case: dict, vendor: M.Vendor, req: dict) -> tuple[bool, str]:
        acct = req.get("new_account")
        if not acct or not account_format_ok(acct):
            return False, "new account number fails format/checksum validation"
        for other in self.registry.all():
            if other.vendor_id != vendor.vendor_id and other.bank_account == acct:
                return False, f"account is already registered to a different vendor ({other.name})"
        return True, ""

    def timeout_to_next(self, case_id: str, current_channel: str) -> Optional[str]:
        case = self.store.get(case_id)
        self._log(case, "TIMEOUT", f"No reply on {current_channel}; escalating.", channel=current_channel)
        self.store.put(case)
        i = CHANNEL_ORDER.index(current_channel) if current_channel in CHANNEL_ORDER else -1
        for nxt in CHANNEL_ORDER[i + 1:]:
            if dict(case["plan"]["channels"]).get(nxt):
                return nxt
        return None


class LocalRunner:
    """Mirrors the Step Functions machine in-process. `replies` maps channel -> reply (or None = silence)."""

    def __init__(self, guardian: Guardian):
        self.g = guardian

    def run(self, raw, replies: dict, auth_results=None, case_id=None) -> dict:
        case = self.g.open_case(raw, auth_results, case_id)
        if case["state"] != M.HELD:
            return case
        cid = case["case_id"]
        channel = next((c for c, _ in case["plan"]["channels"]), None)
        while channel:
            sent = self.g.send_verification(cid, channel)
            reply = replies.get(channel) if sent["sent"] else None
            if reply:
                interp = self.g.handle_reply(cid, text=reply.get("text", ""),
                                             button_id=reply.get("button", ""), channel=channel)
                return self.g.finalize(cid, interp.label if not interp.needs_human else "ESCALATE")
            channel = self.g.timeout_to_next(cid, channel)
        return self.g.finalize(cid, "ESCALATE")
