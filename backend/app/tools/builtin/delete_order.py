from pydantic import BaseModel, Field

class DeleteOrderArgs(BaseModel):
    order_id: str = Field(description="要删除的订单 ID。必填，删除前请确认订单号正确。")
    reason: str = Field(description="删除原因，需明确具体（如 用户误下单 / 重复订单）。必填。")

DESCRIPTION = (
    "删除指定订单（critical 高风险操作，需进入审批中心审批通过后才会执行）。"
    "返回删除结果：order_id、reason、status。"
    "注意：仅当确认订单号正确且删除原因明确时才能调用；审批驳回时订单不会被删除。"
)

def delete_order(order_id: str, reason: str) -> dict:
    return {"order_id": order_id, "reason": reason, "status": "deleted"}
