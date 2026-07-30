from pydantic import BaseModel


class HandlerCandidateData(BaseModel):
    employee_id: int
    name: str
    mobile: str | None


class HandlerCandidateListData(BaseModel):
    items: list[HandlerCandidateData]
    auto_selected_employee_id: int | None
