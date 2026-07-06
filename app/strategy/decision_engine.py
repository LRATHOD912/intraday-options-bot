def decide_final_trade(call_decision, put_decision):
    call_valid = call_decision.get("trade_valid", False)
    put_valid = put_decision.get("trade_valid", False)
    call_score = call_decision.get("score", 0)
    put_score = put_decision.get("score", 0)

    if call_valid and put_valid:
        if call_score > put_score:
            return {
                "decision": "CALL",
                "reason": "Both valid, CALL has higher score",
                "score": call_score,
                "details": call_decision,
            }
        if put_score > call_score:
            return {
                "decision": "PUT",
                "reason": "Both valid, PUT has higher score",
                "score": put_score,
                "details": put_decision,
            }
        return {
            "decision": "NO TRADE",
            "reason": "Both CALL and PUT valid with same score. Conflict detected.",
            "score": call_score,
            "details": {
                "call": call_decision,
                "put": put_decision,
            },
        }

    if call_valid:
        return {
            "decision": "CALL",
            "reason": call_decision.get("reason"),
            "score": call_score,
            "details": call_decision,
        }

    if put_valid:
        return {
            "decision": "PUT",
            "reason": put_decision.get("reason"),
            "score": put_score,
            "details": put_decision,
        }

    return {
        "decision": "NO TRADE",
        "reason": "No valid setup",
        "score": max(call_score, put_score),
        "details": {
            "call": call_decision,
            "put": put_decision,
        },
    }
