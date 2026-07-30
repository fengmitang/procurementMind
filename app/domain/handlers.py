from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HandlerCandidate:
    employee_id: int
    name: str
    mobile: str | None
