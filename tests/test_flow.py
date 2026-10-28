import pytest
from fakes import FakeSes, FakeSms, FakeSocial, wa_payload
from guardian.channels.messenger import Messenger
from guardian.engine import Guardian, LocalRunner
from guardian.models import Vendor
from guardian.registry import InMemoryRegistry
from guardian.store import InMemoryCaseStore

GOOD_IBAN = "GB82WEST12345698765432"
NEW_IBAN = "DE89370400440532013000"

FRAUD = f"""From: Accounts <billing@northwlnd-supply.example>
Reply-To: billing@northwlnd-supply.example
Subject: URGENT: Northwind Supply bank change
Content-Type: text/plain

Hello, Northwind Supply has changed bank. Please pay today's invoice USD 48,000 to
IBAN {NEW_IBAN}. Bank: Fastcash Bank. Do not call the old number, confirm on +91 98765 43210 immediately.
"""

LEGIT = f"""From: ar@northwind-supply.example
Subject: Updated remittance details
Content-Type: text/plain

Northwind Supply is moving banks. New IBAN {NEW_IBAN}. Bank: Harbor Bank. Invoice USD 4,800.
"""

def build(sms_fail=False):
    v = Vendor("v1", "Northwind Supply", ["northwind-supply.example"], "+442071230001", "+442071230001",
               "ap@buyer.example", GOOD_IBAN, "Old Bank", 5000)
    v2 = Vendor("v2", "Other Co", ["other.example"], "+442071230002", None, "ap@buyer.example", "FR1420041010050500013M02606")
    reg = InMemoryRegistry([v, v2])
    s, sm, se = FakeSocial(), FakeSms(sms_fail), FakeSes()
    m = Messenger(s, sm, se, whatsapp_origination_id="phone-number-id-1", sms_origination="+15550000", from_address="g@buyer.example")
    return Guardian(reg, InMemoryCaseStore(), m), reg, s, sm, se


def test_fraud_blocked_and_contacts_come_from_registry():
    g, reg, social, sms, ses = build()
    case = LocalRunner(g).run(FRAUD, {"whatsapp": {"button": "GUARDIAN_DENIED:x"}})
    assert case["state"] == "BLOCKED"
    assert reg.get("v1").bank_account == GOOD_IBAN               # untouched
    sent = wa_payload(social.calls[0])
    assert sent["to"] == "442071230001"                          # registered number, not +91...
    assert "919876543210" not in str(social.calls)
    codes = {s["code"] for s in case["risk"]["signals"]}
    assert {"BANK_ACCOUNT_CHANGE", "UNREGISTERED_CONTACT_SUPPLIED",
            "PAYMENT_AND_VERIFICATION_CONTACT_CHANGE", "SENDER_DOMAIN_NOT_SEEN"} <= codes
    assert case["risk"]["level"] == "HIGH"
    assert ses.calls and ses.calls[-1]["Destination"]["ToAddresses"] == ["ap@buyer.example"]


def test_legit_change_approved_via_same_path():
    g, reg, social, *_ = build()
    case = LocalRunner(g).run(LEGIT, {"whatsapp": {"button": "GUARDIAN_AUTHORIZED:x"}})
    assert case["state"] == "APPROVED"
    assert reg.get("v1").bank_account == NEW_IBAN


def test_silence_falls_back_to_sms_then_escalates():
    g, reg, social, sms, ses = build()
    case = LocalRunner(g).run(LEGIT, {})
    assert case["state"] == "ESCALATED"
    assert len(social.calls) == 1 and len(sms.calls) == 1
    assert sms.calls[0]["DestinationPhoneNumber"] == "+442071230001"
    assert reg.get("v1").bank_account == GOOD_IBAN


def test_sms_reply_after_whatsapp_silence_approves():
    g, reg, *_ = build()
    case = LocalRunner(g).run(LEGIT, {"sms": {"text": "YES"}})
    assert case["state"] == "APPROVED"


def test_conditional_yes_never_auto_approves():
    g, reg, *_ = build()
    case = LocalRunner(g).run(LEGIT, {"whatsapp": {"text": "yes but only if the invoice matches the PO"}})
    assert case["state"] == "ESCALATED"
    assert reg.get("v1").bank_account == GOOD_IBAN


def test_failed_whatsapp_send_falls_through_to_sms():
    g, reg, social, sms, ses = build()
    def boom(**kw): raise RuntimeError("template not approved")
    social.send_whatsapp_message = boom
    case = LocalRunner(g).run(LEGIT, {"sms": {"text": "NO"}})
    assert case["state"] == "BLOCKED"
    assert len(sms.calls) == 1


def test_confirmed_but_account_reused_by_other_vendor_is_escalated():
    g, reg, *_ = build()
    reg.get("v2").bank_account = NEW_IBAN
    case = LocalRunner(g).run(LEGIT, {"whatsapp": {"button": "GUARDIAN_AUTHORIZED:x"}})
    assert case["state"] == "ESCALATED"
    assert reg.get("v1").bank_account == GOOD_IBAN


def test_bad_checksum_account_escalated_even_if_confirmed():
    g, reg, *_ = build()
    bad = LEGIT.replace(NEW_IBAN, "DE89370400440532013001")
    case = LocalRunner(g).run(bad, {"whatsapp": {"button": "GUARDIAN_AUTHORIZED:x"}})
    assert case["state"] == "ESCALATED"


def test_unknown_sender_changes_nothing():
    g, reg, social, *_ = build()
    raw = FRAUD.replace("Northwind Supply", "Acme Unknown").replace("northwlnd-supply", "acme-x")
    case = LocalRunner(g).run(raw, {})
    assert case["state"] == "UNKNOWN_VENDOR"
    assert not social.calls


def test_no_bank_change_no_action():
    g, *_ = build()
    raw = "From: ar@northwind-supply.example\nSubject: Invoice reminder\n\nPlease see the attached invoice."
    case = LocalRunner(g).run(raw, {})
    assert case["state"] == "APPROVED" and "nothing to verify" in case["outcome"].lower()


def test_model_failure_cannot_approve():
    g, reg, *_ = build()
    g.model = lambda t: (_ for _ in ()).throw(RuntimeError("throttled"))
    case = LocalRunner(g).run(LEGIT, {"whatsapp": {"text": "sure thing, go for it"}})
    assert case["state"] == "ESCALATED"


def test_model_low_confidence_approve_is_not_trusted():
    g, reg, *_ = build()
    g.model = lambda t: {"label": "APPROVE", "confidence": 0.6}
    case = LocalRunner(g).run(LEGIT, {"whatsapp": {"text": "sure thing, go for it"}})
    assert case["state"] == "ESCALATED"


def test_whatsapp_template_mode_carries_case_id_in_payloads():
    g, *_ = build()
    g.msg.whatsapp_template = "payee_change_verification"
    p = g.msg.whatsapp_payload("+442071230001", "q", "case-1")
    btns = [c for c in p["template"]["components"] if c["type"] == "button"]
    assert btns[0]["parameters"][0]["payload"] == "GUARDIAN_AUTHORIZED:case-1"


def test_auth_results_read_from_ses_headers():
    from guardian.parser import parse_inbound
    raw = ("From: a@b.example\nAuthentication-Results: amazonses.com; spf=fail smtp.mailfrom=b.example; "
           "dkim=pass; dmarc=fail\nSubject: x\n\nbody")
    r = parse_inbound(raw)
    assert r.auth_results == {"spf": "FAIL", "dkim": "PASS", "dmarc": "FAIL"}


def _email_only(monkeypatch):
    monkeypatch.setenv("ENABLED_CHANNELS", "email")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://guardian.test")


def test_email_link_flow_get_does_not_decide_post_does(monkeypatch):
    _email_only(monkeypatch)
    g, reg, social, sms, ses = build()
    reg.get("v1").email = "supplier-contact@example.com"
    case = g.open_case(LEGIT)
    assert [c for c, _ in case["plan"]["channels"]] == ["email"]
    g.send_verification(case["case_id"], "email", "tok")
    assert not social.calls and not sms.calls
    body = ses.calls[-1]["Content"]["Simple"]["Body"]["Text"]["Data"]
    assert ses.calls[-1]["Destination"]["ToAddresses"] == ["supplier-contact@example.com"]
    c = g.store.get(case["case_id"])
    yes = c["link_tokens"]["yes"]
    assert f"https://guardian.test/v/{yes}" in body
    # a scanner prefetching the link (GET) changes nothing
    assert g.preview_link(yes)["answer"] == "yes"
    assert g.store.get(case["case_id"])["state"] == "VERIFYING"
    case2, interp = g.complete_link(yes)
    g.finalize(case["case_id"], interp.label)
    assert g.store.get(case["case_id"])["state"] == "APPROVED"
    assert g.complete_link(yes) is None            # one-time


def test_email_link_no_blocks_and_burns_both_tokens(monkeypatch):
    _email_only(monkeypatch)
    g, reg, *_ = build()
    reg.get("v1").email = "supplier-contact@example.com"
    case = g.open_case(LEGIT)
    g.send_verification(case["case_id"], "email")
    toks = dict(g.store.get(case["case_id"])["link_tokens"])
    _, interp = g.complete_link(toks["no"])
    g.finalize(case["case_id"], interp.label)
    assert g.store.get(case["case_id"])["state"] == "BLOCKED"
    assert g.preview_link(toks["yes"]) is None


def test_audit_trail_masks_email_and_public_view_hides_tokens(monkeypatch):
    from guardian.handlers.api import _public
    _email_only(monkeypatch)
    g, reg, *_ = build()
    reg.get("v1").email = "supplier-contact@example.com"
    case = g.open_case(LEGIT)
    g.send_verification(case["case_id"], "email", "secret-task-token")
    stored = g.store.get(case["case_id"])
    pub = _public(stored)
    assert "link_tokens" not in pub and "task_token" not in pub and "awaiting_phone" not in pub
    assert "supplier-contact@example.com" not in str(pub)
    assert pub["trusted"]["channels"][0]["to"] == "s***@example.com"


def test_demo_scenarios_are_repeatable_in_any_order(monkeypatch):
    from guardian.demo_data import SCENARIOS, reset_demo, vendors
    monkeypatch.setenv("ENABLED_CHANNELS", "email")
    reg = InMemoryRegistry(vendors(supplier_email="s@example.com"))
    g = Guardian(reg, InMemoryCaseStore(), Messenger(FakeSocial(), FakeSms(), FakeSes(), from_address="g@x.test"))
    for name in ("legit", "fraud", "legit", "fraud"):
        reset_demo(reg)
        c = g.open_case(SCENARIOS[name]["email"], SCENARIOS[name]["auth"])
        assert c["state"] == "HELD", name          # never silently passed through
        g.send_verification(c["case_id"], "email")
        interp = g.handle_reply(c["case_id"], button_id=("GUARDIAN_AUTHORIZED:" if name == "legit" else "GUARDIAN_DENIED:") + c["case_id"], channel="email")
        done = g.finalize(c["case_id"], interp.label)
        assert done["state"] == ("APPROVED" if name == "legit" else "BLOCKED"), name
