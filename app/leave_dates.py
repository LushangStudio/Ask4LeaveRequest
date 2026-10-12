import calendar
from datetime import date,datetime
from zoneinfo import ZoneInfo

def leave_end_limit(today: date | None = None) -> date:
    today=today or datetime.now(ZoneInfo('Asia/Shanghai')).date()
    month_index=today.month-1+3
    year,month=today.year+month_index//12,month_index%12+1
    return date(year,month,min(today.day,calendar.monthrange(year,month)[1]))
