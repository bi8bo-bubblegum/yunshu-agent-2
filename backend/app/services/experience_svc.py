# backend/app/services/experience_svc.py
import logging
from datetime import date
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.experience import Experience
from app.repositories.experience_repo import ExperienceRepository
from app.services.embedding import embed_texts
from app.llm.factory import ModelFactory

logger = logging.getLogger(__name__)

class DistillOutput(BaseModel):
    """经验提炼结构化输出"""
    title: str | None = Field(default=None, description="标题，无价值时为 null")
    summary: str = Field(default="", description="要点摘要")
    content: str = Field(default="", description="完整决策过程")
    tags: list[str] = Field(default_factory=list, description="业务标签")
    event_time: date | None = Field(default=None, description="事件日期 YYYY-MM-DD，营销/策略类必填")
    result_metrics: dict | None = Field(default=None, description="效果指标，营销/策略类必填")

# 经验价值判定提示词（严格化）：
# 老版本只有一句「提炼有价值的历史决策/策略/教训」，LLM 对任何对话（含纯数据查询、
# 闲聊）都会给 title → 经验中心堆积大量无用经验。现明确列出【无价值】场景必须
# title=null，只保留「明确业务动作 + 决策依据/结果 + 可复用」的经验。
DISTILL_PROMPT = (
    "你是企业经验提炼器。从对话中提炼【可复用的业务经验】：某次实际业务决策/操作中"
    "形成的、未来同类场景可复用的方法、策略或教训。\n"
    "\n"
    "## 以下场景判定为【无价值】，title 必须为 null（summary/content 可为空）：\n"
    "1. 纯数据查询：查销售/营收/排班/活动状态/上座率/线路信息等——只获取信息，"
    "没有形成可复用的方法或决策；\n"
    "2. 信息问答：询问规则、价格、定义、工具用法等——没有业务决策；\n"
    "3. 闲聊寒暄：问候、致谢、无业务实质的交流；\n"
    "4. 无结果的建议：给出了方案但没有执行、没有结果反馈、没有形成结论；\n"
    "5. 单句状态通知：如「已创建」「已发布」等，无可复用的决策过程。\n"
    "\n"
    "## 有价值经验的必要条件：对话包含【明确的业务动作 + 决策依据或结果】，"
    "且未来同类场景可复用。示例：\n"
    "- 给某线路节假日加密班次，上座率提升 20% → 策略经验；\n"
    "- 活动预算按渠道三七分配，ROI 达 5 → 决策经验；\n"
    "- query_lines 查全量数据会超时，应带筛选条件查询 → 工具使用教训。\n"
    "\n"
    "## 输出要求：\n"
    "- 无价值 → title=null；\n"
    "- 有价值 → title 简洁概括（≤20 字），summary 提炼可复用要点，content 记录决策过程；\n"
    "- 营销/策略类必须包含 event_time 和 result_metrics，否则视为无价值，title 设为 null。\n"
    "\n"
    "对话：\n{text}"
)

# 经验提炼用的对话窗口：取最近 max_rounds 轮 user/assistant 文本（多轮上下文），
# 截断到 max_chars（保留最新）。单轮问答缺少业务过程上下文，纯查询会被误判为经验。
DIALOG_MAX_ROUNDS = 6
DIALOG_MAX_CHARS = 6000


async def build_experience_dialog(db: AsyncSession, conv_id: str) -> str:
    """从会话消息构造经验提炼用的多轮对话文本（跳过 tool 标记消息）。

    经验判断需要完整业务过程：单轮「用户问/助手答」缺少上下文，纯查询也会被误判
    为经验。取最近 DIALOG_MAX_ROUNDS 轮 user/assistant 文本（旧→新），保留最近
    DIALOG_MAX_CHARS 字符（多轮优先保留新内容）。"""
    from app.repositories.conversation_repo import MessageRepository
    msgs = await MessageRepository(db).list_by_conversation(conv_id)
    lines: list[str] = []
    for m in reversed(msgs):
        if m.role not in ("user", "assistant"):
            continue  # 跳过 tool 标记消息等非对话角色
        content = (m.content or "").strip()
        if not content:
            continue
        lines.append(("用户" if m.role == "user" else "助手") + "：" + content)
        if len(lines) >= DIALOG_MAX_ROUNDS * 2:
            break
    lines.reverse()  # 恢复时间顺序（旧→新）
    dialog = "\n".join(lines)
    if len(dialog) > DIALOG_MAX_CHARS:
        dialog = dialog[-DIALOG_MAX_CHARS:]
    return dialog


async def distill_experience(text: str, user_id: str, trace_id: str) -> Experience | None:
    llm = ModelFactory.get_llm().with_structured_output(DistillOutput)
    prompt = DISTILL_PROMPT.format(text=text[:6000])
    # LLM 偶发返回非法日期（如 0000-01-01）会导致 pydantic 校验失败，
    # 重试一次并强调日期约束；仍失败则放弃本条经验，不影响聊天主流程
    result = None
    for attempt, extra in enumerate((
        "",
        "\n注意：event_time 必须是 1900-01-01 至 2100-12-31 之间的真实日期（如 2024-10-01），"
        "禁止使用 0000-01-01 等非法日期；没有有效日期时置为 null。",
    )):
        try:
            result = await llm.ainvoke(prompt + extra)
            break
        except Exception as e:
            logger.warning("经验提炼 LLM 输出校验失败（第 %d 次）: %s", attempt + 1, e)
    if not result.title:
        return None
    vec = (await embed_texts([f"{result.title} {result.summary}"]))[0]
    return Experience(
        owner_id=user_id, scope="personal", status="draft",
        title=result.title, summary=result.summary, content=result.content,
        tags=result.tags, event_time=result.event_time, result_metrics=result.result_metrics,
        source_trace_id=trace_id, embedding=vec,
    )

async def save_personal_experience(db: AsyncSession, exp: Experience) -> None:
    repo = ExperienceRepository(db)
    await repo.add(exp)
    await repo.commit()
