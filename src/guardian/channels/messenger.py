"""The three AWS Communication Developer Services clients used by the system.

  * socialmessaging         -> send_whatsapp_message   (AWS End User Messaging Social)
  * pinpoint-sms-voice-v2   -> send_text_message       (AWS End User Messaging SMS)
  * sesv2                   -> send_email              (Amazon SES)

Clients are injectable so the same code runs against real AWS and against test fakes.
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

META_API_VERSION = "v20.0"
BTN_YES = "GUARDIAN_AUTHORIZED"
BTN_NO = "GUARDIAN_DENIED"


def _client(name: str, region: Optional[str] = None):
    import boto3  # imported lazily so pure-logic code and tests need no AWS SDK
    return boto3.client(name, region_name=region or os.environ.get("AWS_REGION", "us-east-1"))


def verification_question(vendor_name: str, case_id: str, masked_account: str, masked_old: str) -> str:
    return (f"[{vendor_name}] Payment-details check {case_id}: we received a request to change your "
            f"payee bank account from {masked_old} to {masked_account}. "
            "Did YOUR organisation authorise this change?")


class Messenger:
    def __init__(self, social=None, sms=None, ses=None, *, whatsapp_origination_id: str = "",
                 sms_origination: str = "", from_address: str = "",
                 whatsapp_template: str = "", sms_config_set: str = ""):
        self._social, self._sms, self._ses = social, sms, ses
        self.whatsapp_origination_id = whatsapp_origination_id or os.environ.get("WHATSAPP_ORIGINATION_ID", "")
        self.sms_origination = sms_origination or os.environ.get("SMS_ORIGINATION_IDENTITY", "")
        self.from_address = from_address or os.environ.get("SES_FROM_ADDRESS", "")
        self.whatsapp_template = whatsapp_template or os.environ.get("WHATSAPP_TEMPLATE", "")
        self.sms_config_set = sms_config_set or os.environ.get("SMS_CONFIG_SET", "")

    # lazy clients
    @property
    def social(self):
        if self._social is None:
            self._social = _client("socialmessaging")
        return self._social

    @property
    def sms(self):
        if self._sms is None:
            self._sms = _client("pinpoint-sms-voice-v2")
        return self._sms

    @property
    def ses(self):
        if self._ses is None:
            self._ses = _client("sesv2")
        return self._ses

    # ---- WhatsApp (End User Messaging Social) ----
    def whatsapp_payload(self, to: str, text: str, case_id: str) -> dict:
        to = to.lstrip("+")
        if self.whatsapp_template:
            # Business-initiated messages need an approved template with quick-reply buttons.
            return {
                "messaging_product": "whatsapp", "to": to, "type": "template",
                "template": {
                    "name": self.whatsapp_template, "language": {"code": "en"},
                    "components": [
                        {"type": "body", "parameters": [{"type": "text", "text": text[:900]}]},
                        {"type": "button", "sub_type": "quick_reply", "index": "0",
                         "parameters": [{"type": "payload", "payload": f"{BTN_YES}:{case_id}"}]},
                        {"type": "button", "sub_type": "quick_reply", "index": "1",
                         "parameters": [{"type": "payload", "payload": f"{BTN_NO}:{case_id}"}]},
                    ],
                },
            }
        return {
            "messaging_product": "whatsapp", "to": to, "type": "interactive",
            "interactive": {
                "type": "button", "body": {"text": text[:1000]},
                "action": {"buttons": [
                    {"type": "reply", "reply": {"id": f"{BTN_YES}:{case_id}", "title": "Yes, we authorised"}},
                    {"type": "reply", "reply": {"id": f"{BTN_NO}:{case_id}", "title": "No, we did NOT"}},
                ]},
            },
        }

    def send_whatsapp(self, to: str, text: str, case_id: str) -> str:
        payload = self.whatsapp_payload(to, text, case_id)
        resp = self.social.send_whatsapp_message(
            originationPhoneNumberId=self.whatsapp_origination_id,
            metaApiVersion=META_API_VERSION,
            message=json.dumps(payload).encode("utf-8"),
        )
        return resp.get("messageId", "")

    # ---- SMS (End User Messaging SMS) ----
    def send_sms(self, to: str, text: str, case_id: str) -> str:
        body = f"{text} Reply YES {case_id} to confirm or NO {case_id} to deny."
        kwargs: dict[str, Any] = dict(
            DestinationPhoneNumber=to, OriginationIdentity=self.sms_origination,
            MessageBody=body, MessageType="TRANSACTIONAL",
        )
        if self.sms_config_set:
            kwargs["ConfigurationSetName"] = self.sms_config_set
        return self.sms.send_text_message(**kwargs).get("MessageId", "")

    # ---- Email (SES v2) ----
    def send_email(self, to: str, subject: str, body: str) -> str:
        resp = self.ses.send_email(
            FromEmailAddress=self.from_address,
            Destination={"ToAddresses": [to]},
            Content={"Simple": {"Subject": {"Data": subject, "Charset": "UTF-8"},
                                "Body": {"Text": {"Data": body, "Charset": "UTF-8"}}}},
        )
        return resp.get("MessageId", "")

    def send_on(self, channel: str, to: str, text: str, case_id: str) -> str:
        if channel == "whatsapp":
            return self.send_whatsapp(to, text, case_id)
        if channel == "sms":
            return self.send_sms(to, text, case_id)
        if channel == "email":
            return self.send_email(to, f"Action needed: payment change {case_id}", text)
        raise ValueError(f"unknown channel {channel}")
