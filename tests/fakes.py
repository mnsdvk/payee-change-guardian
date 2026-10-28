import json


class FakeSocial:
    def __init__(self): self.calls = []
    def send_whatsapp_message(self, **kw):
        self.calls.append(kw); return {"messageId": "wamid.TEST"}


class FakeSms:
    def __init__(self, fail=False): self.calls = []; self.fail = fail
    def send_text_message(self, **kw):
        if self.fail: raise RuntimeError("blocked")
        self.calls.append(kw); return {"MessageId": "sms-1"}


class FakeSes:
    def __init__(self): self.calls = []
    def send_email(self, **kw):
        self.calls.append(kw); return {"MessageId": "ses-1"}


def wa_payload(call): return json.loads(call["message"])
