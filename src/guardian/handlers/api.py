"""Dashboard + judge-testing API (HTTP API -> this Lambda)."""
import base64
import json
import os
import pathlib

from .common import guardian
from .ingest import start_case
from .reply import deliver
from ..demo_data import SCENARIOS, reset_demo

HTML = (pathlib.Path(__file__).parent.parent / "static" / "dashboard.html").read_text()


PRIVATE_KEYS = ("task_token", "link_tokens", "awaiting_phone", "plan")


def _public(case):
    """Strip anything that could be used to answer a case or reveal contact details."""
    if not case:
        return case
    out = {k: v for k, v in case.items() if k not in PRIVATE_KEYS}
    req = dict(out.get("request", {}))
    req["supplied_contacts"] = req.get("supplied_contacts", [])
    out["request"] = req
    return out


def _resp(code, body, ctype="application/json"):
    return {"statusCode": code, "headers": {"content-type": ctype, "cache-control": "no-store"},
            "body": body if isinstance(body, str) else json.dumps(body, default=str)}


PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Payment details check</title><body style="font:16px system-ui;max-width:32rem;margin:2rem auto;padding:0 1rem">
<h2>{title}</h2><p>{body}</p>{form}</body>"""


def _page(code, title, body, form=""):
    import html
    return _resp(code, PAGE.format(title=html.escape(title), body=html.escape(body), form=form), "text/html")


def _link_routes(g, method, path):
    token = path.split("/v/", 1)[1].strip("/")
    info = g.preview_link(token)
    if not info:
        return _page(410, "This link is no longer valid",
                     "It was already used or the request is closed. No change was made by opening it.")
    if method == "GET":
        yes = info["answer"] == "yes"
        q = (f"{info['vendor']}: we received a request to change your payee bank account to "
             f"{info['new_account']}.")
        btn = "Yes, we authorised this change" if yes else "No, we did NOT authorise this"
        form = f'<form method="post"><button style="font:inherit;padding:.7rem 1rem">{btn}</button></form>'
        return _page(200, "Confirm your answer", q + " Press the button to send your answer.", form)
    out = g.complete_link(token)
    if not out:
        return _page(410, "This link is no longer valid", "It was already used or the request is closed.")
    case, interp = out
    decision = "ESCALATE" if interp.needs_human else interp.label
    tok = case.get("task_token")
    if tok:
        from .common import sfn
        sfn().send_task_success(taskToken=tok, output=json.dumps({"decision": decision}))
    return _page(200, "Thank you", "Your answer was recorded. You can close this page.")


def handler(event, _ctx):
    method = event["requestContext"]["http"]["method"]
    path = event.get("rawPath", "/")
    g = guardian()
    if path.startswith("/v/") and method in ("GET", "POST"):
        return _link_routes(g, method, path)
    if method == "GET" and path == "/":
        return _resp(200, HTML, "text/html")
    if method == "GET" and path == "/api/cases":
        return _resp(200, [_public(c) for c in g.store.list()[:50]])
    if method == "POST" and path.startswith("/api/cases/") and path.endswith("/analyze"):
        import os
        cid = path.split("/")[3]
        if g.claim_ai_note(cid, force=bool(json.loads(event.get("body") or "{}").get("force"))):
            fn = os.environ.get("AI_FUNCTION_NAME")
            if fn:        # hand off to the background worker so a slow model never holds up a request
                import boto3
                boto3.client("lambda").invoke(FunctionName=fn, InvocationType="Event",
                                              Payload=json.dumps({"case_id": cid}).encode())
            else:
                g.run_ai_note(cid)
        c = g.store.get(cid)
        return _resp(200 if c else 404, _public(c) or {"error": "not found"})
    if method == "GET" and path.startswith("/api/cases/"):
        c = g.store.get(path.rsplit("/", 1)[-1])
        return _resp(200 if c else 404, _public(c) or {"error": "not found"})
    if method == "GET" and path == "/api/status":
        import os
        prov = os.environ.get("AI_PROVIDER") or ("bedrock" if os.environ.get("BEDROCK_MODEL_ID") else "")
        return _resp(200, {"ai": prov or None, "model": os.environ.get("AI_MODEL", ""),
                           "channels": os.environ.get("ENABLED_CHANNELS", "")})
    if method == "POST" and path == "/api/reset":
        g.store.clear()          # demo convenience: wipe cases and restore the trusted supplier record
        reset_demo(g.registry)
        return _resp(200, {"ok": True})
    if method == "POST" and path == "/api/scenarios":
        name = json.loads(event.get("body") or "{}").get("scenario")
        if name not in SCENARIOS:
            return _resp(400, {"error": "unknown scenario"})
        reset_demo(g.registry)   # demo only: every run starts from the same trusted record
        case = start_case(SCENARIOS[name]["email"].encode(), SCENARIOS[name].get("auth"))
        return _resp(200, {"case_id": case["case_id"]})
    if method == "POST" and path == "/api/simulate-reply":
        # Judge convenience when no phone is at hand. Uses the SAME reply path, and is
        # clearly labelled as simulated in the audit trail.
        b = json.loads(event.get("body") or "{}")
        c = g.store.get(b.get("case_id", ""))
        if not c or c["state"] != "VERIFYING":
            return _resp(409, {"error": "case not awaiting reply"})
        g._log(c, "SIMULATED_REPLY", "Reply injected from the dashboard (no phone).")
        g.store.put(c)
        r = deliver({"channel": c.get("awaiting_channel", "whatsapp"), "phone": c["awaiting_phone"],
                     "text": str(b.get("text", ""))[:300] if b.get("text") else "",
                     "button": ("TEXT:" if b.get("text") else
                                "GUARDIAN_AUTHORIZED:" if b.get("answer") == "yes" else "GUARDIAN_DENIED:") + c["case_id"]})
        return _resp(200, r)
    return _resp(404, {"error": "not found"})
