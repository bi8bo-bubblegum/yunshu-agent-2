# backend/app/services/tool_cards.py
"""结构化工具卡片落库辅助。

一次图执行到达终态后，把 ToolCallRecorder 收集到的工具调用转成
独立 Message（role="tool"）一次性落库，供前端持久化渲染工具卡片。
"""
from app.models.chat import Message


def tool_message_rows(conversation_id: str, recorder) -> list[Message]:
    """把 ToolCallRecorder 转成待落库的 tool 消息列表。

    仅终态记录落库（running 跳过）：high/critical interrupt 工具只发 start
    不发 end，若中断时就落 pending 卡片，resume 重放会重复。status 只有
    success/error，running 只存在于流式实时卡片。
    """
    rows = []
    for rec in recorder.order:
        if rec.get("status") == "running":
            continue
        rows.append(Message(
            conversation_id=conversation_id,
            role="tool",
            content=f"🔧 {rec['tool']}",
            metadata_={
                "kind": "tool",
                "tool": rec["tool"],
                "args": rec.get("args"),
                "result": rec.get("result"),
                "status": rec.get("status", "success"),
            },
        ))
    return rows
