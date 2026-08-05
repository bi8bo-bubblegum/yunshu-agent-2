# backend/app/tools/risk.py
"""风险等级判定工具。
- 内置工具 risk 在注册时硬编码声明（facade.register）
- MCP 工具 risk 运行时动态注入：get_mcp_risk()
- 风险分流判定：needs_confirmation / needs_approval（供 facade.to_langchain_tool 复用）"""


def needs_confirmation(risk: str) -> bool:
    """high 风险：interrupt 即时确认（不进审批中心）。"""
    return risk == "high"


def needs_approval(risk: str) -> bool:
    """critical 风险：创建审批单，进审批中心等管理者审批。"""
    return risk == "critical"


def get_mcp_risk(tool_name: str, server_default_risk: str, server_config: dict) -> str:
    """判定 MCP 工具的风险等级（运行时动态注入）。
    优先级：工具级覆盖 config.tool_risks > 服务级 default_risk > "medium" 兜底。
    内置工具的 risk 在注册时硬编码声明，不走本函数。"""
    tool_risks = (server_config or {}).get("tool_risks", {})
    return tool_risks.get(tool_name, server_default_risk or "medium")