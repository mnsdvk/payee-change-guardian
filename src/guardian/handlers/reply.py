"""Inbound replies. Subscribed to the WhatsApp (End User Messaging Social) and two-way SMS SNS topics."""
import json
import re

from ..parser import normalise_phone
from .common import guardian, sfn

CASE_RE = re.compile(r"case-[0-9a-f]{6,}", re.I)


def _whatsapp_messages(body: dict):
    entry = body.get("whatsAppWebhookEntry")
    if isinstance(entry, str):
        entry = json.loads(entry)
    for ch in (entry or {}).get("changes", []):
        for m in ch.get("value", {}).get("messages", []):
            yield m


def parse_whatsapp(m: dict) -> dict:
    t = m.get("type")
    out = {"channel": "whatsapp", "phone": normalise_phone("+" + m.get("from", "")), "text": "", "button": ""}
    if t == "button":
        out["button"] = m["button"].get("payload", "")
    elif t == "interactive":
        out["button"] = m["interactive"].get("button_reply", {}).get("id", "")
    elif t == "text":
        out["text"] = m["text"].get("body", "")
    return out


def parse_sms(body: dict) -> dict:
    return {"channel": "sms", "phone": normalise_phone(body.get("originationNumber", "")),
            "text": body.get("messageBody", ""), "button": ""}


def deliver(reply: dict) -> dict:
    g = guardian()
    cid = None
    for src in (reply["button"], reply["text"]):
        m = CASE_RE.search(src or "")
        if m:
            cid = m.group(0).lower()
            break
    case = g.store.get(cid) if cid else g.store.find_open_by_phone(reply["phone"])
    if not case or case["state"] != "VERIFYING":
        return {"ignored": True}
    # The reply only counts if it comes from the number WE messaged (registered contact).
    if reply["phone"] != case.get("awaiting_phone"):
        g._log(case, "REPLY_REJECTED", "Reply came from a number that is not the registered contact.")
        g.store.put(case)
        return {"ignored": True}
    interp = g.handle_reply(case["case_id"], reply["text"], reply["button"], reply["channel"])
    decision = "ESCALATE" if interp.needs_human else interp.label
    token = case.get("task_token")
    if token:
        sfn().send_task_success(taskToken=token, output=json.dumps({"decision": decision}))
    return {"decision": decision}


def handler(event, _ctx):
    results = []
    for rec in event.get("Records", []):
        body = json.loads(rec["Sns"]["Message"])
        if "whatsAppWebhookEntry" in body:
            for m in _whatsapp_messages(body):
                results.append(deliver(parse_whatsapp(m)))
        elif "messageBody" in body:
            results.append(deliver(parse_sms(body)))
    return results
