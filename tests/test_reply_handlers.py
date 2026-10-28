import json
from guardian.handlers.reply import parse_sms, parse_whatsapp, _whatsapp_messages


def test_whatsapp_template_button_event():
    entry = {"changes": [{"value": {"messages": [
        {"from": "442071230001", "type": "button", "button": {"payload": "GUARDIAN_DENIED:case-abc123", "text": "No"}}]}}]}
    body = {"whatsAppWebhookEntry": json.dumps(entry)}
    r = parse_whatsapp(next(_whatsapp_messages(body)))
    assert r["button"] == "GUARDIAN_DENIED:case-abc123" and r["phone"] == "+442071230001"


def test_whatsapp_interactive_reply_event():
    m = {"from": "442071230001", "type": "interactive",
         "interactive": {"button_reply": {"id": "GUARDIAN_AUTHORIZED:case-abc123"}}}
    assert parse_whatsapp(m)["button"].startswith("GUARDIAN_AUTHORIZED")


def test_sms_two_way_event():
    r = parse_sms({"originationNumber": "+442071230001", "messageBody": "NO case-abc123"})
    assert r["text"] == "NO case-abc123" and r["phone"] == "+442071230001"
