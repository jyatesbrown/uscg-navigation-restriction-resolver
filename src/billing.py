from __future__ import annotations

from .models.output import Billing, ResultStatus

EVENT_NAME = "navigation-area-check"


def billing_decision(status: ResultStatus, matched: int) -> Billing:
    if status == "success":
        return Billing(billable=True, event_name=EVENT_NAME, reason="All requested layers checked.")
    if status == "partial" and matched > 0:
        return Billing(
            billable=True,
            event_name=EVENT_NAME,
            reason="Some layers failed, but matching notices were found in the layers checked.",
        )
    if status == "partial":
        return Billing(billable=False, reason="Zero matches with incomplete layer coverage is not charged.")
    return Billing(billable=False, reason=f"Not charged: status {status}.")
