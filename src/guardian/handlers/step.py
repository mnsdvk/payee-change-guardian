"""Single Lambda behind the Step Functions states: send | timeout | finalize."""
from .common import guardian, sfn


def handler(event, _ctx):
    g, action, cid = guardian(), event["action"], event["case_id"]
    if action == "send":
        res = g.send_verification(cid, event["channel"], event["token"])
        if not res["sent"]:
            # nothing will ever call back for this token, so release the state machine now
            sfn().send_task_success(taskToken=event["token"],
                                    output='{"decision":"SEND_FAILED"}')
        return res
    if action == "timeout":
        g.timeout_to_next(cid, event["channel"])
        return {"decision": "NO_REPLY"}
    if action == "finalize":
        case = g.finalize(cid, event["decision"])
        try:
            from ..events import EventPublisher
            EventPublisher().publish(case)
        except Exception:
            pass
        return {"state": case["state"]}
    raise ValueError(action)
