# backend/app/tools/builtin/__init__.py
from app.tools.facade import DataFacade, Tool
from app.tools.builtin.query_sales_data import QuerySalesDataArgs, query_sales_data, DESCRIPTION as QUERY_SALES_DESC
from app.tools.builtin.query_marketing_campaigns import QueryMarketingCampaignsArgs, query_marketing_campaigns, DESCRIPTION as QUERY_CAMP_DESC
from app.tools.builtin.query_schedule import QueryScheduleArgs, query_schedule, DESCRIPTION as QUERY_SCHED_DESC
from app.tools.builtin.create_marketing_campaign import CreateMarketingCampaignArgs, create_marketing_campaign, DESCRIPTION as CREATE_CAMP_DESC
from app.tools.builtin.adjust_schedule import AdjustScheduleArgs, adjust_schedule, DESCRIPTION as ADJUST_SCHED_DESC
from app.tools.builtin.publish_campaign import PublishCampaignArgs, publish_campaign, DESCRIPTION as PUBLISH_CAMP_DESC
from app.tools.builtin.delete_order import DeleteOrderArgs, delete_order, DESCRIPTION as DELETE_ORDER_DESC
from app.tools.builtin.search_knowledge import SearchKnowledgeArgs, search_knowledge, DESCRIPTION as SEARCH_KB_DESC

def register_builtin_tools(f: DataFacade) -> None:
    # risk 字段先声明，任务 31 增强时用于风险分级包装
    f.register(Tool("query_sales_data", query_sales_data, "low", QUERY_SALES_DESC, QuerySalesDataArgs))
    f.register(Tool("query_marketing_campaigns", query_marketing_campaigns, "low", QUERY_CAMP_DESC, QueryMarketingCampaignsArgs))
    f.register(Tool("query_schedule", query_schedule, "low", QUERY_SCHED_DESC, QueryScheduleArgs))
    # 创建活动 = 提交 OA 审批表单：critical 进审批中心，审批通过后才真正创建活动
    #（真实创建逻辑后续替换 mock；publish_campaign 同理在审批通过后真实发帖）
    f.register(Tool("create_marketing_campaign", create_marketing_campaign, "critical", CREATE_CAMP_DESC, CreateMarketingCampaignArgs))
    f.register(Tool("adjust_schedule", adjust_schedule, "high", ADJUST_SCHED_DESC, AdjustScheduleArgs))
    f.register(Tool("publish_campaign", publish_campaign, "critical", PUBLISH_CAMP_DESC, PublishCampaignArgs))
    f.register(Tool("delete_order", delete_order, "critical", DELETE_ORDER_DESC, DeleteOrderArgs))
    # 知识库检索：低风险查询类，agent 主动调用（不再自动装配）
    f.register(Tool("search_knowledge", search_knowledge, "low", SEARCH_KB_DESC, SearchKnowledgeArgs))
