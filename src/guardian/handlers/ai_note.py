"""Background worker: writes the advisory AI note for a case. Never touches the decision."""
from .common import guardian


def handler(event, _ctx):
    guardian().run_ai_note(event["case_id"])
    return {"ok": True}
