"""One status aggregation rule for a batch's planning and worker receipts."""


def render_state(statuses):
    states = set(statuses)
    for state in ("running", "cancelling", "queued", "failed", "cancelled", "completed"):
        if state in states:
            return "running" if state == "cancelling" else state
    return "unknown"
