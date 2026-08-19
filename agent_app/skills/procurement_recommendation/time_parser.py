import calendar
import re
from datetime import date, timedelta

from agent_app.skills.procurement_recommendation.schemas import RecommendationTimeRange

_RELATIVE_PATTERN = re.compile(r"(?:近|最近)\s*(\d+)\s*个?\s*(天|周|月|年)")
_EXPLICIT_PATTERN = re.compile(
    r"(\d{4}-\d{1,2}-\d{1,2})\s*(?:到|至|~|—|-)\s*(\d{4}-\d{1,2}-\d{1,2})"
)


def parse_time_range(message: str, *, today: date | None = None) -> RecommendationTimeRange:
    current = today or date.today()
    explicit = _EXPLICIT_PATTERN.search(message)
    if explicit:
        start = date.fromisoformat(explicit.group(1))
        end = date.fromisoformat(explicit.group(2))
        if start <= end:
            return RecommendationTimeRange(
                start=start, end=end, description=f"{start.isoformat()} 至 {end.isoformat()}"
            )
    relative = _RELATIVE_PATTERN.search(message)
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        if amount > 0:
            if unit == "天":
                start = current - timedelta(days=amount)
            elif unit == "周":
                start = current - timedelta(weeks=amount)
            elif unit == "月":
                start = _subtract_months(current, amount)
            else:
                start = _subtract_months(current, amount * 12)
            return RecommendationTimeRange(
                start=start, end=current, description=f"近{amount}{unit}"
            )
    if "本月" in message:
        return RecommendationTimeRange(
            start=current.replace(day=1), end=current, description="本月"
        )
    if "今年" in message or "本年" in message:
        return RecommendationTimeRange(
            start=current.replace(month=1, day=1), end=current, description="今年"
        )
    return RecommendationTimeRange()


def _subtract_months(value: date, months: int) -> date:
    total = value.year * 12 + value.month - 1 - months
    year, month_index = divmod(total, 12)
    month = month_index + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
