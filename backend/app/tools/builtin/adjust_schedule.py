from pydantic import BaseModel, Field

class AdjustScheduleArgs(BaseModel):
    shift_id: str = Field(description="要调整的班次 ID")
    employee_id: str = Field(description="员工 ID")
    new_date: str = Field(description="调整后的日期 YYYY-MM-DD")
    new_time: str = Field(description="调整后的时间段，如 '08:00-16:00'")

DESCRIPTION = "调整员工排班班次。Mock 返回调整结果，不写真实数据库。"

def adjust_schedule(shift_id: str, employee_id: str, new_date: str, new_time: str) -> dict:
    return {"shift_id": shift_id, "employee_id": employee_id,
            "new_date": new_date, "new_time": new_time, "status": "adjusted"}