"""One shared commerce domain service for Harness, Codex and Hermes."""
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import re
import sqlite3
import hashlib
from commerce_core import Core, PLATFORMS
from operations_analysis import unit_economics, restock_plan, input_schema, UNIT_FIELDS, STOCK_FIELDS
from packing_estimate import estimate as packing_estimate, definitions as packing_definitions
from shipping_workbench import ShippingWorkbench, definitions as shipping_definitions
from order_imports import OrderImports, definitions as order_import_definitions
from workflow_plan import WorkflowPlans, definitions as workflow_plan_definitions
from operating_pipeline import OperatingPipeline, definitions as operating_pipeline_definitions
from operating_budget import OperatingBudget, definitions as operating_budget_definitions
from mobile_control import MobileControl, definitions as mobile_control_definitions
from operating_control import OperatingControl, definitions as operating_control_definitions
from media_library import MediaLibrary, definitions as media_library_definitions
from intel_opportunities import IntelOpportunities, definitions as intel_opportunity_definitions
from ozon_search_terms import OzonSearchTerms, definitions as ozon_search_terms_definitions
from layered_memory import LayeredMemory, definitions as memory_definitions
from knowledge_ranking import ranked_notes
from research import template as collection_template, validate as collection_check, export as collection_export, digest, canonical
from translation import TranslationJobs
from intelligence import Intelligence
from intel_articles import Articles
from intel_article_batches import ArticleBatches, definitions as article_batch_definitions
from intel_reading import IntelReading, definitions as intel_reading_definitions
from intel_dashboard import IntelDashboard, definitions as intel_dashboard_definitions
from intel_live import IntelLive, definitions as intel_live_definitions
from public_web import PublicWeb, definitions as public_web_definitions
from article_review import ArticleReviews
from collection_jobs import CollectionJobs
from collection_registry import REGISTRY as CRAWLER_REGISTRY
from ops_alerts import OperationsAlerts
from campaign_plans import compare as campaign_compare
from live_connections import LiveConnections
from ozon_accounts import OzonAccounts
from channel_connections import ChannelConnections, definitions as channel_definitions
from model_providers import ModelRegistry, definitions as model_definitions
from live_planning import LivePlanning
from creative_studio import CreativeStudio, tool_definitions as creative_tools
from creative_workflow import CreativeWorkflow, definitions as media_definitions
from media_providers import MediaProviders, definitions as media_provider_definitions
from media_plugin_connections import MediaPluginConnections, definitions as media_plugin_definitions
from media_plugin_execution import MediaPluginExecution, definitions as media_plugin_execution_definitions
from extension_runtime import ExtensionRuntime
from extension_runtime.contracts import definitions as extension_definitions
from capability_lifecycle import CapabilityLifecycle
from capability_tasks import CapabilityTasks
from capability_setup import open_setup as capability_open_setup
from phone_management import open_in_browser as phone_open
from product_catalog import ProductCatalog, definitions as catalog_definitions
from product_evidence import ProductEvidence, definitions as product_evidence_definitions
from product_evidence_media import definitions as product_evidence_media_definitions
from catalog_sync import CatalogSync, definitions as catalog_sync_definitions
from listing_actions import ListingActions, definitions as listing_actions_definitions
from owner_review import OwnerReviews, definitions as owner_review_definitions
from listing_submissions import ListingSubmissions, definitions as listing_submission_definitions
from cost_scenarios import CostScenarios, definitions as cost_scenarios_definitions
from listing_workspace import ListingWorkspace, definitions as listing_definitions
from store_scopes import StoreScopes, definitions as store_scope_definitions
from execution_history import ExecutionHistory, tools as execution_history_tools
from order_support import OrderSupport, definitions as order_support_definitions
from storefront_drafts import StorefrontDrafts, definitions as storefront_draft_definitions
from listing_reconciliation import ListingReconciliation, definitions as listing_reconciliation_definitions
from listing_schema import ListingSchema, definitions as listing_schema_definitions
from listing_release import ListingReleases, definitions as listing_release_definitions
from sealeap_library import SkillLibrary, definitions as skill_tools
from autonomy import Autonomy
from organization import Organization
from organization_exchange import definitions as exchange_definitions
from knowledge_io import read_note
from agent_runtime import AgentRuntime, definitions as agent_definitions
from exposure import Exposure, definitions as exposure_definitions
from platform_connections import PlatformConnections, definitions as platform_definitions
from pilot_bridge import PilotBridge, definitions as pilot_definitions
from social_intel.store import SocialStore, definitions as social_definitions
from business_workflows import BusinessWorkflows, definitions as business_definitions
from workflow_continuity import WorkflowContinuity, definitions as workflow_definitions
from copilot import Copilot, definitions as copilot_definitions
from assistant_team import AssistantTeams, definitions as assistant_team_definitions
from engineering import EngineeringTeam, definitions as engineering_definitions
from assistant_speech import SpeechReader, definitions as assistant_speech_definitions
from tool_discovery import ToolDiscovery, definitions as tool_discovery_definitions
from form_drafts import FormDrafts, definitions as form_draft_definitions
from product_workspace import ProductWorkspace, definitions as workspace_definitions
from a2ui.cost import CostSurfaces, definitions as a2ui_definitions, dispatch as a2ui_dispatch
from market_research import MarketResearch, definitions as market_research_definitions
from host_execution import HostExecution, definitions as host_execution_definitions
from attention import Attention, definitions as attention_definitions
from followups import Followups, definitions as followup_definitions
from chain_budget import ChainBudget, definitions as chain_budget_definitions
from task_timeline import TaskTimeline, definitions as timeline_definitions

LABELS=dict(zip(PLATFORMS,['Ozon','TikTok Shop','Amazon','Mercado Libre','Temu']))
SALES=[39200,34800,28640,18000,8000]
MARKETS=dict(zip(PLATFORMS,['RU','US','US','MX','待选择']))


def now():return datetime.now(timezone.utc).isoformat()


def schema(properties=None,required=None):
    return {'type':'object','properties':properties or {},'required':required or [],'additionalProperties':False}


S={'type':'string','minLength':1,'maxLength':160}
FILTERS={'demo':{'type':'boolean'},'platform':{'type':'string','enum':['all',*PLATFORMS]},'store_id':{'type':'string','enum':['all','ozon-live',*(p+'-demo'for p in PLATFORMS)]},'market':{'type':'string','enum':['all','RU','US','MX']}}
INTEL_QUERY={'query':{'type':'string','maxLength':100},'source':{'type':'string','enum':['all','usgs','gdacs','wto','fed','ecb','eia','hmrc','transport']},'category':{'type':'string','enum':['all','earthquake','disaster','trade','macro','energy','logistics']},'country':{'type':'string','maxLength':80},'hours':{'type':'string','enum':['all','1','6','24','48','168']},'scope':{'type':'string','enum':['latest','archive']},'view':{'type':'string','enum':['all','unviewed','bookmarked']}}
TOOLS=[
 ('commerce_ozon_accounts_list','只读已保存Ozon账号及当前单活连接；不返回凭据、不切换店铺、不并行同步',schema()),
 ('commerce_ozon_account_status','只读准确Ozon账号的本地配置与快照归属；不调用平台或切换店铺',schema({'account_id':S},['account_id'])),
 ('commerce_runtime_status','读取独立运行时、公共采集计划与本地执行器状态；不等于平台已授权',schema()),
 ('commerce_runtime_configure','启停固定公开源定时采集；不会启用飞书或店铺写操作',schema({'enabled':{'type':'boolean'},'interval_seconds':{'type':'string','enum':['300','900','1800','3600']}},['enabled'])),
 ('commerce_task_execute','明确请求本地操作：简报、情报证据整理或成本/补货测算；自由描述不会作为指令执行',schema({'task_id':S,'operation':{'type':'string','enum':['report','intel_review','unit_economics','restock_plan']}},['task_id','operation'])),
 ('commerce_task_result','读取本地执行回执、结果及待追问事项',schema({'task_id':S},['task_id'])),
 ('commerce_task_retry','明确重试失败或中断的本地任务；不重发平台操作',schema({'task_id':S},['task_id'])),
 ('commerce_organization_board','只读检查本项目岗位门禁、真实缺项与责任；不代表商业闭环成功',schema({'case_id':S})),
 ('commerce_organization_import_inventory','从已保存库存建立本地工作项；保留未知币种和来源状态，不操作店铺',schema()),
 ('commerce_organization_currency','明确本地工作项金额币种；不换算或改价',schema({'case_id':S,'currency':{'type':'string','pattern':'^[A-Z]{3}$'}},['case_id','currency'])),
 ('commerce_organization_record','按工作项保存调研、供应链或经济测算资料；不接受自报 PASS 结论',schema({'case_id':S,'kind':{'type':'string','enum':['research','supply','economics']},'payload':{'type':'object'},'idempotency_key':S},['case_id','kind','payload','idempotency_key'])),
 ('commerce_organization_deliver','将已登记图片按显式工作项交付到本机 outbox 并验证哈希；不发布素材',schema({'case_id':S,'project_id':S,'asset_ids':{'type':'array','items':{'type':'string'},'minItems':1,'maxItems':20},'idempotency_key':S},['case_id','project_id','asset_ids','idempotency_key'])),
 ('commerce_organization_brief','读取某一岗位的范围、缺项、产物契约与复验步骤',schema({'case_id':S,'stage_id':S},['case_id','stage_id'])),
 ('commerce_organization_handoff','按当前缺项创建可去重本地任务；创建或完成任务不自动关闭门禁',schema({'case_id':S,'stage_id':S},['case_id','stage_id'])),
 ('commerce_organization_capture','保存当前本机体检快照及 JSON/Markdown/HTML，供后续复查',schema({'case_id':S})),
 ('commerce_status','查看共享后台、五平台与连接状态',schema()),
 ('commerce_dashboard','读取经营指标；demo=true 仅返回明确标注的模拟数据',schema(FILTERS)),
 ('commerce_orders_list','查询订单；未授权时真实订单为空。指定import_batch_id只读取已确认本机导入行，不表示平台同步。',schema({**FILTERS,'query':{'type':'string','maxLength':100},'status':{'type':'string','maxLength':40},'import_batch_id':S})),
 ('commerce_products_list','查询商品与库存；原币与 SKU 保留来源',schema(FILTERS)),
 ('commerce_task_create','创建可跨工具查询的任务；不会自动执行平台写操作',schema({'idempotency_key':S,'kind':{'type':'string','enum':['report','analysis','draft']},'input':{'type':'object'}},['idempotency_key','kind'])),
 ('commerce_task_list','读取所有客户端共用的任务队列',schema()),
 ('commerce_task_get','按任务 ID 查询同一任务',schema({'task_id':S},['task_id'])),
 ('commerce_task_cancel','取消尚未执行的共享任务',schema({'task_id':S},['task_id'])),
 ('commerce_report_create','生成本地运营简报草稿；不发消息、不修改店铺',schema({**FILTERS,'period':{'type':'string','enum':['30']},'idempotency_key':S},['idempotency_key'])),
 ('commerce_knowledge_list','列出已配置业务知识目录中的 Markdown 文件',schema()),
 ('commerce_knowledge_read','读取所选目录内的业务 Markdown；禁止路径穿越和软链接',schema({'path':S},['path'])),
 ('commerce_knowledge_search','在所选业务目录内搜索；不扫描整个 Vault',schema({'query':{'type':'string','minLength':1,'maxLength':80}},['query'])),
 ('commerce_summary_save','将简报草稿归档到配置的 Obsidian 业务目录',schema({'report_id':S},['report_id'])),
 ('commerce_reports_list','查看共用的本地运营简报草稿',schema()),
 ('commerce_unit_economics','用明确提供的同币种成本计算单件贡献草稿；缺参数返回 HOLD，不内置平台费率',schema({'input':input_schema(UNIT_FIELDS)},['input'])),
 ('commerce_restock_plan','按明确提供的销量窗口与库存计算补货草稿；不创建采购单或修改库存',schema({'input':input_schema(STOCK_FIELDS)},['input'])),
 ('commerce_collection_template','读取平台采集清单与中英证据模板；不是平台上架规则',schema({'platform':{'type':'string','enum':['research',*PLATFORMS]}},['platform'])),
 ('commerce_collection_check','检查采集缺项、译文校对、数字差异和证据；不证明真实性',schema({'record':{'type':'object'}},['record'])),
 ('commerce_collection_export','生成包含原文、中文、来源与哈希的 JSON/CSV 文件内容；不完整时拒绝正式导出',schema({'record':{'type':'object'},'final':{'type':'boolean'}},['record'])),
 ('commerce_translation_start','使用现有 Hermes 模型翻译所选原文，产生待校对译文；无工具执行',schema({'input':{'type':'object'},'idempotency_key':S},['input','idempotency_key'])),
 ('commerce_translation_get','查询同一翻译任务与模型来源、数字差异；不自动重发',schema({'job_id':S},['job_id'])),
 ('commerce_crawler_start','启动固定公开源多路采集并导入；串行队列、可取消，无店铺写操作',schema({'source':{'type':'string','enum':['all',*CRAWLER_REGISTRY]},'idempotency_key':S},['source','idempotency_key'])),
 ('commerce_crawler_list','读取采集队列、逐来源进度和已导入结果',schema()),
 ('commerce_crawler_alert_ack','确认已查看本机采集失败告警；保留失败记录，不重试任务',schema({'alert_id':S},['alert_id'])),
 ('commerce_crawler_endurance_status','读取真实24小时采集验收进度；未满时长或监测中断不算通过',schema()),
 ('commerce_crawler_storage','读取私有采集证据容量、预警与归档摘要',schema()),
 ('commerce_crawler_archive','校验并压缩符合保留策略的历史成功任务；失败证据保留',schema()),
 ('commerce_crawler_archive_verify','校验某份本机归档的清单、文件哈希与完整性',schema({'archive_id':S},['archive_id'])),
 ('commerce_crawler_get','读取指定采集任务',schema({'job_id':S},['job_id'])),
 ('commerce_crawler_cancel','取消剩余采集；已完成的来源快照保留',schema({'job_id':S},['job_id'])),
 ('commerce_crawler_retry','明确重试失败、取消或中断的采集任务，递增尝试次数',schema({'job_id':S},['job_id'])),
 ('commerce_intel_article_reviews','读取原文/译文绑定的追加修订与复核记录；不改原始模型输出',schema({'article_id':S},['article_id'])),
 ('commerce_intel_article_record','追加重新检查、中文修订或明确复核声明；检查通过不自动审核',schema({'article_id':S,'operation':{'type':'string','enum':['recheck','revision','review']},'idempotency_key':S,'base_sha256':S,'zh':{'type':'string','maxLength':60000},'note':{'type':'string','maxLength':2000},'decision':{'type':'string','enum':['approved','needs_changes']},'confirmed':{'type':'boolean'}},['article_id','operation','idempotency_key','base_sha256'])),
 ('commerce_intel_article_start','采集所选记录的发布方正文，双路核对并绑定原记录版本；不下载附件',schema({'item_id':S,'record_sha256':S,'idempotency_key':S},['item_id','record_sha256','idempotency_key'])),
 ('commerce_intel_article_get','读取正文、原文哈希、来源证据和待校对中文；保留原始版本',schema({'article_id':S},['article_id'])),
 ('commerce_intel_article_list','读取所选记录已留存的正文版本',schema({'item_id':S},['item_id'])),
 ('commerce_intel_article_translate','通过已配置 Hermes 翻译所选正文；分段保留来源绑定，机器译文待校对',schema({'article_id':S},['article_id'])),
 ('commerce_intel_sources','查看全球公开信息源的覆盖、采集时间、失败和陈旧状态',schema()),
 ('commerce_intel_search','分页检索当前快照或本机积累；支持收藏和未查看，不是全网历史搜索',schema({**INTEL_QUERY,'limit':{'type':'string','enum':['20','50','100']},'cursor':{'type':'string','maxLength':400},'include_map':{'type':'boolean'},'map_limit':{'type':'integer','minimum':1,'maximum':5000},'include_panels':{'type':'boolean'},'map_layers':{'type':'array','items':{'type':'string'},'maxItems':10},'bounds':{'type':'object'},'link_map':{'type':'boolean'}})),
 ('commerce_intel_item_get','读取公开来源记录、采集凭据与本地版本摘要；不标记为已查看',schema({'item_id':S},['item_id'])),
 ('commerce_intel_item_update','收藏或按明确版本标记已查看；不表示事实已核实',schema({'item_id':S,'action':{'type':'string','enum':['viewed','unviewed','bookmark','unbookmark']},'record_sha256':S},['item_id','action'])),
 ('commerce_intel_review_create','按已展示的来源版本创建共享核查任务，同版本重复调用复用任务；不会执行店铺操作',schema({'item_id':S,'record_sha256':S},['item_id','record_sha256'])),
 ('commerce_intel_watch_save','保存共享检索条件，最多12项；不启用自动采集或消息推送',schema({'name':{'type':'string','minLength':1,'maxLength':60},**INTEL_QUERY},['name'])),
 ('commerce_intel_watch_list','读取共享关注主题、匹配和未查看数量；不是推送状态',schema()),
 ('commerce_intel_watch_remove','移除指定的共享检索条件；保留记录和收藏',schema({'watch_id':S},['watch_id'])),
 ('commerce_intel_refresh','更新公开来源：读取固定源并导入本机多路采集快照；失败保留旧数据，90秒限频，不访问店铺',schema({'source':{'type':'string','enum':['all','usgs','gdacs','wto','fed','ecb','eia','hmrc','transport']}})),
 ('commerce_worldmonitor_status','查看 World Monitor 接入准备状态；discover=true 仅发现官方公开工具表，不调用收费数据工具',schema({'discover':{'type':'boolean'}})),
 ('commerce_phone_open','在本机浏览器打开已鉴权手机管理；不开始控制或修改设备',schema()),
 ('commerce_ui_get_preferences','读取当前本机用户共享的界面主题偏好',schema()),
 ('commerce_ui_set_preferences','保存浅色、深色或跟随系统偏好；不改变业务数据',schema({'theme':{'type':'string','enum':['light','dark','system']}},['theme'])),
 ('commerce_ops_record','保存带来源的订单或库存观察；手工导入不等于平台同步，不发送通知',schema({'record':{'type':'object'},'demo':{'type':'boolean'}},['record'])),
 ('commerce_ops_list','查看去重后的出单、履约和补货提醒及数据陈旧状态',schema({'demo':{'type':'boolean'}})),
 ('commerce_ops_ack','将本地提醒标为已阅，不代表已完成履约或补货',schema({'alert_id':S,'demo':{'type':'boolean'}},['alert_id'])),
 ('commerce_ops_rules','读取或保存本地提醒规则；不改变平台或消息渠道',schema({'rules':{'type':'object'},'demo':{'type':'boolean'}})),
 ('commerce_ops_export','导出本地提醒的来源记录、规则、哈希和状态历史',schema({'demo':{'type':'boolean'}})),
 ('commerce_campaign_compare','比较定价、商家优惠、每单广告与达人佣金的单件贡献草稿',schema({'input':{'type':'object'}},['input'])),
 ('commerce_live_status','读取 Ozon/飞书接入状态，绝不返回密钥',schema()),
 ('commerce_live_open_setup','在本机默认浏览器打开私有接入向导；密钥不经过聊天',schema()),
 ('commerce_live_sync','启动一次已配置 Ozon 的只读同步；不修改店铺',schema()),
 ('commerce_live_alerts','读取 Ozon 真实快照的待处理订单与低库存提醒',schema()),
 ('commerce_live_ack','将真实数据提醒标为已阅，不改变平台状态',schema({'alert_id':S},['alert_id'])),
 ('commerce_live_readiness','查看接入缺项、快照有效性与最近通知回执；desktop范围将手机通知列为后置，不发送消息',schema({'scope':{'type':'string','enum':['all','desktop']}})),
 ('commerce_live_restock_list','查看精确商品和履约范围的库存候选与已保存补货草稿',schema()),
 ('commerce_live_restock_save','按当前库存快照和手工销量资料保存本地补货草稿，不采购或修改库存',schema({'row_key':{'type':'string','minLength':1,'maxLength':240},'source_sha256':S,'input':{'type':'object'},'idempotency_key':S},['row_key','source_sha256','input','idempotency_key'])),
 ('commerce_live_restock_export','导出补货草稿、中文字段说明与来源证据，标明当前是否已失效',schema({'plan_id':S},['plan_id'])),
 ('commerce_live_export','导出当前 Ozon 只读快照、中文字段说明与通知回执证据，不含凭据和买家身份',schema()),
]


TOOLS.extend(creative_tools(schema, S))
TOOLS.extend(media_definitions(schema,S))
TOOLS.extend(media_provider_definitions(schema,S))
TOOLS.extend(media_plugin_definitions(schema,S))
TOOLS.extend(media_plugin_execution_definitions(schema,S))
TOOLS.extend(extension_definitions(schema,S))
TOOLS.append(('commerce_capability_open_setup','在本机浏览器打开媒体模型服务与插件的私有接入设置',schema()))
TOOLS.extend(catalog_definitions(schema,S))
TOOLS.extend(product_evidence_definitions(schema,S))
TOOLS.extend(product_evidence_media_definitions(schema,S))
TOOLS.extend(catalog_sync_definitions(schema,S))
TOOLS.extend(listing_actions_definitions(schema,S))
TOOLS.extend(owner_review_definitions(schema,S))
TOOLS.extend(listing_submission_definitions(schema,S))
TOOLS.extend(cost_scenarios_definitions(schema,S))
TOOLS.extend(listing_definitions(schema,S))
TOOLS.extend(storefront_draft_definitions(schema,S))
TOOLS.extend(listing_reconciliation_definitions(schema,S))
TOOLS.extend(listing_schema_definitions(schema,S))
TOOLS.extend(listing_release_definitions(schema,S))
TOOLS.extend(skill_tools(schema, S))
TOOLS.extend(agent_definitions(schema, S))
TOOLS.extend(exposure_definitions(schema, S))
TOOLS.extend(intel_reading_definitions(schema, S))
TOOLS.extend(article_batch_definitions(schema,S))
TOOLS.extend(intel_dashboard_definitions(schema, S))
TOOLS.extend(intel_live_definitions(schema, S))
TOOLS.extend(public_web_definitions(schema,S))
TOOLS.extend(platform_definitions(schema, S))
TOOLS.extend(pilot_definitions(schema, S))
TOOLS.extend(social_definitions(schema, S))
TOOLS.extend(exchange_definitions(schema, S))
TOOLS.extend(business_definitions(schema))
TOOLS.extend(workflow_definitions(schema,S,FILTERS))
TOOLS.extend(copilot_definitions(schema,S))
TOOLS.extend(assistant_team_definitions(schema,S))
TOOLS.extend(assistant_speech_definitions(schema,S))
TOOLS.extend(tool_discovery_definitions(schema,S))
TOOLS.extend(form_draft_definitions(schema))
TOOLS.extend(workspace_definitions(schema,S))
TOOLS.extend(a2ui_definitions(schema))
TOOLS.extend(channel_definitions(schema,S))
TOOLS.extend(market_research_definitions(schema,S))
TOOLS.extend(host_execution_definitions(schema,S))
TOOLS.extend(attention_definitions(schema,S))
TOOLS.extend(followup_definitions(schema,S))
TOOLS.extend(chain_budget_definitions(schema,S))
TOOLS.extend(timeline_definitions(schema,S))
TOOLS.extend(media_library_definitions(schema,S))
TOOLS.extend(intel_opportunity_definitions(schema,S))
TOOLS.extend(ozon_search_terms_definitions(schema,S))
TOOLS.extend(model_definitions(schema,S))
TOOLS.extend(packing_definitions(schema))
TOOLS.extend(shipping_definitions(schema))
TOOLS.extend(order_import_definitions(schema))
TOOLS.extend(workflow_plan_definitions(schema))
TOOLS.extend(operating_pipeline_definitions(schema,S))
TOOLS.extend(operating_budget_definitions(schema,S))
TOOLS.extend(mobile_control_definitions(schema,S))
TOOLS.extend(operating_control_definitions(schema,S))
TOOLS.extend(memory_definitions(schema))
TOOLS.extend(store_scope_definitions(schema,S))
TOOLS.extend(execution_history_tools(schema))
TOOLS.extend(order_support_definitions(schema))
TOOLS.extend(engineering_definitions(schema))


class Commerce:
    def __init__(self,state):
        self.state=Path(state).resolve();self.state.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.core=Core(self.state/'commerce.sqlite')
        with self.core.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS reports (id TEXT PRIMARY KEY, idem TEXT UNIQUE, mode TEXT, content TEXT, created_at TEXT)')
            c.execute('CREATE TABLE IF NOT EXISTS clients (name TEXT PRIMARY KEY, seen_at TEXT)')
        self.translations=TranslationJobs(self.core)
        self.intelligence=Intelligence(self.core)
        self.intel_reading=IntelReading(self.core,self.intelligence,self.translations)
        self.intel_dashboard=IntelDashboard(self.core)
        self.intel_live=IntelLive(self.core,self.state)
        self.collections=CollectionJobs(self.core,self.state,importer=self.intelligence.import_collection)
        self.articles=Articles(self.core,self.state,self.intelligence,self.translations)
        self.article_reviews=ArticleReviews(self.core,self.articles)
        self.article_batches=ArticleBatches(self)
        with self.core.db() as db:db.execute('CREATE TABLE IF NOT EXISTS ui_preferences (id TEXT PRIMARY KEY, theme TEXT NOT NULL)')
        self.operations=OperationsAlerts(self.core)
        self.shipping=ShippingWorkbench(self.core)
        self.live=LiveConnections(self.core,self.state)
        self.ozon_accounts=OzonAccounts(self.live)
        if self.ozon_accounts.journal.exists():self.ozon_accounts.recover()
        self.channels=ChannelConnections(self.core)
        self.live_plans=LivePlanning(self.live)
        self.creative=CreativeStudio(self.core,self.state)
        self.skills=SkillLibrary(self.core,self.state,tool_catalog=lambda:TOOLS)
        self.autonomy=Autonomy(self)
        self.organization=Organization(self)
        self.exposure=Exposure(self)
        self.platforms=PlatformConnections(self)
        self.pilots=PilotBridge(self)
        self.social=SocialStore(self)
        self.models=ModelRegistry(self)
        self.agent_runtime=AgentRuntime(self)
        self.public_web=PublicWeb(self.state)
        self.business=BusinessWorkflows(self)
        self.workflow=WorkflowContinuity(self)
        self.copilot=Copilot(self)
        self.market_research=MarketResearch(self)
        self.host_execution=HostExecution(self)
        self.attention=Attention(self)
        self.followups=Followups(self)
        self.chain_budget=ChainBudget(self)
        self.task_timeline=TaskTimeline(self)
        self.form_drafts=FormDrafts(self.core)
        self.product_workspace=ProductWorkspace(self)
        self.catalog=ProductCatalog(self)
        self.media_library=MediaLibrary(self)
        self.intel_opportunities=IntelOpportunities(self)
        self.ozon_search_terms=OzonSearchTerms(self)
        self.product_evidence=ProductEvidence(self)
        self.catalog_sync=CatalogSync(self)
        self.listing_actions=ListingActions(self)
        self.cost_scenarios=CostScenarios(self)
        self.media=CreativeWorkflow(self)
        self.media_providers=MediaProviders(self)
        self.media_plugins=MediaPluginConnections(self)
        self.media_plugin_execution=MediaPluginExecution(self)
        self.extensions=ExtensionRuntime(self)
        self.capability_lifecycle=CapabilityLifecycle(self)
        self.capability_tasks=CapabilityTasks(self)
        self.listings=ListingWorkspace(self)
        self.storefront_drafts=StorefrontDrafts(self)
        self.listing_reconciliation=ListingReconciliation(self)
        self.listing_schema=ListingSchema(self)
        self.listing_releases=ListingReleases(self)
        self.owner_reviews=OwnerReviews(self)
        self.listing_submissions=ListingSubmissions(self)
        self.order_imports=OrderImports(self)
        self.workflow_plans=WorkflowPlans(self)
        self.operating_pipeline=OperatingPipeline(self)
        self.operating_budget=OperatingBudget(self.core)
        self.mobile_control=MobileControl(self, budget_reader=lambda:self.operating_control.mobile_budget())
        self.operating_control=OperatingControl(self)
        self.memory=LayeredMemory(self)
        self.store_scopes=StoreScopes(self)
        self.execution_history=ExecutionHistory(self)
        self.order_support=OrderSupport(self)
        self.assistant_team=AssistantTeams(self)
        self.engineering=EngineeringTeam(self)
        self.assistant_speech=SpeechReader(self)
        self.tool_discovery=ToolDiscovery(self)
        self.a2ui=CostSurfaces(self.core, unit_economics, workspace=self.product_workspace)

    def validate(self,name,args):
        definition=next((x[2]for x in TOOLS if x[0]==name),None)
        if definition is None:raise ValueError('unknown_tool')
        if not isinstance(args,dict) or set(args)-set(definition['properties']) or any(k not in args for k in definition['required']):raise ValueError('invalid_arguments')
        for key,value in args.items():
            rule=definition['properties'][key];typ=rule['type']
            if (typ=='string' and not isinstance(value,str))or(typ=='boolean' and not isinstance(value,bool))or(typ=='object' and not isinstance(value,dict)):raise ValueError('invalid_'+key)
            if typ=='string' and not rule.get('minLength',0)<=len(value)<=rule.get('maxLength',20000):raise ValueError('invalid_'+key)
            if 'enum'in rule and value not in rule['enum']:raise ValueError('invalid_'+key)

    def config(self):
        path=self.state/'config.json'
        return json.loads(path.read_text()) if path.exists() else {}

    def root(self):
        value=self.config().get('knowledge_root')
        if not value:return None
        p=Path(value)
        if not p.is_absolute() or not p.is_dir() or p.is_symlink():raise ValueError('knowledge_root_invalid')
        return p.resolve()

    def safe_note(self,relative):
        root=self.root()
        if root is None:raise ValueError('knowledge_not_configured')
        path=Path(relative)
        if path.is_absolute() or '..'in path.parts or path.suffix!='.md':raise ValueError('invalid_note_path')
        target=root/path
        if any(p.is_symlink() for p in [target,*target.parents] if p!=root.parent) or not target.resolve().is_relative_to(root):raise ValueError('invalid_note_path')
        if not target.is_file() or target.stat().st_size>128000:raise ValueError('note_unavailable')
        return target

    def notes(self):
        root=self.root()
        if root is None:return []
        result=[]
        for folder,dirs,files in os.walk(root,followlinks=False):
            dirs[:]=sorted(d for d in dirs if not d.startswith('.') and not (Path(folder)/d).is_symlink())
            for f in sorted(files):
                p=Path(folder)/f
                if f.endswith('.md') and not p.is_symlink() and p.stat().st_size<=128000:result.append(str(p.relative_to(root)))
                if len(result)>=200:return result
        return result

    def invoke(self,name,args,client='local'):
        self.validate(name,args)
        if client not in ['codex','hermes','harness','browser','local','test']:raise ValueError('invalid_client')
        with self.core.db() as c:c.execute('INSERT OR REPLACE INTO clients VALUES (?,?)',(client,now()))
        if name=='commerce_ozon_accounts_list':return self.ozon_accounts.listing()
        if name=='commerce_ozon_account_status':return self.ozon_accounts.status(**args)
        if name in ('commerce_web_search','commerce_web_read'):return self.public_web.invoke(name,args)
        if name=='commerce_packing_estimate':return packing_estimate(args['input'])
        if name.startswith('commerce_shipping_'):return self.shipping.invoke(name,args)
        if name.startswith('commerce_order_import_'):return self.order_imports.invoke(name,args)
        if name.startswith('commerce_workflow_plan_'):return self.workflow_plans.invoke(name,args)
        if name.startswith('commerce_operating_pipeline_'):return self.operating_pipeline.invoke(name,args)
        if name.startswith('commerce_operating_budget_'):return self.operating_budget.invoke(name,args)
        if name.startswith('commerce_operating_control_'):return self.operating_control.invoke(name,args)
        if name=='commerce_media_library_list':return self.media_library.invoke(name,args)
        if name.startswith('commerce_intel_opportunity_'):return self.intel_opportunities.invoke(name,args)
        if name.startswith('commerce_ozon_search_terms_'):return self.ozon_search_terms.invoke(name,args)
        if name in ('commerce_mobile_command','commerce_mobile_receipt_get','commerce_mobile_decision_get','commerce_mobile_project'):return self.mobile_control.invoke(name,args)
        if name.startswith('commerce_memory_'):return self.memory.invoke(name,args)
        if name=='commerce_orders_list' and args.get('import_batch_id'):return self.order_imports.orders(args['import_batch_id'],args)
        if name=='commerce_model_list':return self.models.catalog()
        if name=='commerce_execution_hosts':return self.host_execution.listing()
        if name.startswith('commerce_attention_'):return self.attention.invoke(name,args)
        if name.startswith('commerce_followup_'):return self.followups.invoke(name,args)
        if name=='commerce_chain_budget_get':return self.chain_budget.summary(**args)
        if name=='commerce_task_timeline_get':return self.task_timeline.get(**args)
        if name=='commerce_model_open_setup':return self.models.open_setup()
        if name=='commerce_capability_open_setup':return capability_open_setup(self)
        if name=='commerce_phone_open':return phone_open(self)
        if name=='commerce_extension_tools_discover':return self.tool_discovery.invoke(name,args)
        if name.startswith('commerce_assistant_team_'):return self.assistant_team.invoke(name,args)
        if name.startswith('commerce_engineering_'):return self.engineering.invoke(name,args)
        if name=='commerce_assistant_speech':return self.assistant_speech.invoke(name,args)
        if name.startswith('commerce_extension_'):return self.extensions.invoke(name,args)
        if name.startswith('commerce_copilot_'):return self.copilot.invoke(name,args)
        if name.startswith('commerce_market_research_'):return self.market_research.invoke(name,args)
        if name.startswith('commerce_form_draft_'):return self.form_drafts.invoke(name,args)
        if name.startswith('commerce_workspace_'):return self.product_workspace.invoke(name,args)
        if name.startswith('commerce_product_evidence_'):return self.product_evidence.invoke(name,args)
        if name.startswith('commerce_a2ui_'):return a2ui_dispatch(self.a2ui,name,args)
        if name=='commerce_report_create':return self.workflow.report(args)
        if name=='commerce_workflow_task_create':return self.workflow.source_task(args)
        if name=='commerce_task_continue':
            extension_run=self.capability_tasks.find(args['task_id'])
            if extension_run and extension_run.get('_task_owner')=='engineering':raise ValueError('engineering_task_use_execution_controls')
            if extension_run:raise ValueError('media_plugin_task_use_execution_controls' if extension_run.get('_task_owner')=='media_plugin' else 'extension_task_use_capability_runtime')
            return self.workflow.continue_task(args)
        if name=='commerce_execution_history':return self.execution_history.invoke(name,args)
        if name.startswith('commerce_order_support_'):return self.order_support.invoke(name,args)
        if name=='commerce_business_list':return self.order_support.decorate_listing(self.business.listing(**args))
        if name=='commerce_business_get':return self.order_support.decorate(self.business.get(**args))
        if name=='commerce_business_draft':return self.order_support.legacy_draft(**args)
        if name=='commerce_business_review':return self.order_support.review(**args)
        if name=='commerce_business_export':return self.order_support.export(**args)
        if name.startswith('commerce_business_'):return self.business.invoke(name,args)
        if name.startswith('commerce_agent_'):return self.agent_runtime.invoke(name,args)
        if name.startswith('commerce_exposure_'):return self.exposure.invoke(name,args)
        if name.startswith('commerce_storefront_draft_'):return self.storefront_drafts.invoke(name,args)
        if name.startswith('commerce_platform_'):return self.platforms.invoke(name,args)
        if name.startswith('commerce_pilot_'):return self.pilots.invoke(name,args)
        if name.startswith('commerce_social_'):return self.social.invoke(name,args)
        if name.startswith('commerce_organization_exchange_'):return self.organization.exchange.invoke(name,args)
        if name=='commerce_organization_board':return self.organization.board(args.get('case_id'))
        if name=='commerce_organization_import_inventory':return self.organization.import_inventory()
        if name=='commerce_organization_currency':return self.organization.set_currency(**args)
        if name=='commerce_organization_record':return self.organization.record(**args)
        if name=='commerce_organization_deliver':return self.organization.deliver(**args)
        if name=='commerce_organization_brief':return self.organization.brief(**args)
        if name=='commerce_organization_handoff':return self.organization.handoff(**args)
        if name=='commerce_organization_capture':return self.organization.capture(args.get('case_id'))
        if name=='commerce_runtime_status':
            status=self.autonomy.status();work=self.listing_submissions.current
            active=bool(work and work['status']=='running')
            return {**status,'requested_local_work':status['requested_local_work']+int(active),'capability_runtime':self.capability_lifecycle.status(),'listing_submission_work':dict(kind=work['kind'],status=work['status'])if work else None}
        if name=='commerce_runtime_configure':return self.autonomy.configure(**args)
        if name in ('commerce_task_result','commerce_task_cancel','commerce_task_retry','commerce_task_execute','commerce_task_continue'):
            extension_run=self.capability_tasks.find(args['task_id'])
            if extension_run:return self.capability_tasks.invoke(name,extension_run,args)
        if name in ('commerce_task_execute','commerce_task_retry') and self.market_research.owns(args['task_id']):raise ValueError('market_research_resume_required')
        if name=='commerce_task_cancel' and self.market_research.owns(args['task_id']):
            self.market_research.cancel(args['task_id'])
            return self.core.invoke('commerce_task_get',args)
        if name=='commerce_task_execute':return self.autonomy.request(**args)
        if name=='commerce_task_result':return self.market_research.result(**args) if self.market_research.owns(args['task_id']) else self.autonomy.result(**args)
        if name=='commerce_task_retry':return self.autonomy.retry(**args)
        if name.startswith('commerce_store_scope_'):return self.store_scopes.invoke(name,args)
        if name.startswith('commerce_listing_schema_'):return self.listing_schema.invoke(name,args)
        if name.startswith('commerce_owner_review_'):return self.owner_reviews.invoke(name,args)
        if name.startswith('commerce_listing_submission_'):return self.listing_submissions.invoke(name,args)
        if name.startswith('commerce_listing_release_'):return self.listing_releases.invoke(name,args)
        if name.startswith('commerce_listing_action_'):return self.listing_actions.invoke(name,args)
        if name in {d[0]for d in listing_reconciliation_definitions(schema,S)}:return self.listing_reconciliation.invoke(name,args)
        if name.startswith('commerce_listing_') or name=='commerce_store_workbench':return self.listings.invoke(name,args)
        if name.startswith('commerce_catalog_store_'):return self.catalog_sync.invoke(name,args)
        if name.startswith('commerce_cost_scenarios_'):return self.cost_scenarios.invoke(name,args)
        if name.startswith('commerce_catalog_'):return self.catalog.invoke(name,args)
        if name.startswith('commerce_media_plugin_execution_'):return self.media_plugin_execution.invoke(name,args)
        if name.startswith('commerce_media_plugin_'):return self.media_plugins.invoke(name,args)
        if name.startswith('commerce_media_provider_'):return self.media_providers.invoke(name,args)
        if name.startswith('commerce_media_'):return self.media.invoke(name,args)
        if name.startswith('commerce_creative_'):return self.creative.invoke(name,args)
        if name.startswith('commerce_skills_'):return self.skills.invoke(name,args)
        if name=='commerce_live_readiness':return self.live_plans.readiness(**args)
        if name=='commerce_live_restock_list':return self.live_plans.list()
        if name=='commerce_live_restock_save':return self.live_plans.save(**args)
        if name=='commerce_live_restock_export':return self.live_plans.export(args['plan_id'])
        if name=='commerce_channel_status':return self.channels.status(**args)
        if name=='commerce_channel_configure':return self.channels.configure(**args)
        if name=='commerce_live_status':return self.live.status()
        if name=='commerce_live_open_setup':return self.live.open_setup('http://127.0.0.1:'+os.environ.get('COMMERCE_PORT','38731'))
        if name=='commerce_live_sync':return self.live.start_sync()
        if name=='commerce_live_alerts':return self.live.alerts()
        if name=='commerce_live_ack':return self.live.acknowledge(args['alert_id'])
        if name=='commerce_live_export':return self.live.export_evidence()
        if name=='commerce_ui_get_preferences':
            with self.core.db() as db:row=db.execute("SELECT theme FROM ui_preferences WHERE id='local-owner'").fetchone()
            return {'theme':row[0] if row else 'system','scope':'shared_local_owner'}
        if name=='commerce_ui_set_preferences':
            with self.core.db() as db:db.execute("INSERT OR REPLACE INTO ui_preferences VALUES ('local-owner',?)",(args['theme'],))
            return {'theme':args['theme'],'scope':'shared_local_owner'}
        if name=='commerce_ops_record':return self.operations.record(args['record'],args.get('demo',False))
        if name=='commerce_ops_list':return self.operations.list(args.get('demo',False))
        if name=='commerce_ops_ack':return self.operations.acknowledge(args['alert_id'],args.get('demo',False))
        if name=='commerce_ops_rules':return self.operations.rules(args.get('demo',False),args.get('rules'))
        if name=='commerce_ops_export':return self.operations.export(args.get('demo',False))
        if name=='commerce_campaign_compare':return campaign_compare(args['input'])
        if name=='commerce_intel_reading_start':return self.intel_reading.start(**args)
        if name=='commerce_intel_reading_get':return self.intel_reading.get(**args)
        if name=='commerce_intel_dashboard_get':return self.intel_dashboard.get()
        if name=='commerce_intel_dashboard_update':return self.intel_dashboard.update(**args)
        if name=='commerce_intel_live_get':return self.intel_live.get(**args)
        if name=='commerce_intel_live_refresh':return self.intel_live.refresh(**args)
        if name=='commerce_intel_item_get':return self.intel_reading.decorate({'items':[self.intelligence.store.item(**args)]})['items'][0]
        if name=='commerce_intel_item_update':return self.intel_reading.decorate({'items':[self.intelligence.store.update_item(**args)]})['items'][0]
        if name=='commerce_intel_review_create':return self.intelligence.store.create_review(**args)
        if name=='commerce_intel_watch_save':return self.intelligence.store.save_watch(**args)
        if name=='commerce_intel_watch_list':return self.intelligence.store.watches()
        if name=='commerce_intel_watch_remove':return self.intelligence.store.remove_watch(**args)
        if name=='commerce_crawler_start':return self.collections.request(args['source'],args['idempotency_key'])
        if name=='commerce_crawler_list':return self.collections.listing()
        if name=='commerce_crawler_alert_ack':return self.collections.acknowledge(args['alert_id'])
        if name=='commerce_crawler_endurance_status':return self.collections.endurance_status()
        if name=='commerce_crawler_storage':return self.collections.capacity.listing()
        if name=='commerce_crawler_archive':return self.collections.capacity.maintain(force=True)
        if name=='commerce_crawler_archive_verify':return self.collections.capacity.verify(args['archive_id'])
        if name=='commerce_crawler_get':return self.collections.get(args['job_id'])
        if name=='commerce_crawler_cancel':return self.collections.cancel(args['job_id'])
        if name=='commerce_crawler_retry':return self.collections.retry(args['job_id'])
        if name in {d[0] for d in article_batch_definitions(schema,S)}:return self.article_batches.invoke(name,args)
        if name=='commerce_intel_article_reviews':return self.article_reviews.listing(**args)
        if name=='commerce_intel_article_record':return self.article_reviews.record(client=client,**args)
        if name=='commerce_intel_article_start':return self.articles.start(**args)
        if name=='commerce_intel_article_get':return self.articles.get(**args)
        if name=='commerce_intel_article_list':return self.articles.for_item(**args)
        if name=='commerce_intel_article_translate':return self.articles.translate(**args)
        if name=='commerce_intel_sources':return self.intelligence.sources()
        if name=='commerce_intel_search':return self.intel_reading.decorate(self.intelligence.search(**args))
        if name=='commerce_intel_refresh':return self.intelligence.refresh(**args)
        if name=='commerce_worldmonitor_status':return self.intelligence.worldmonitor(**args)
        if name=='commerce_status':
            with self.core.db() as c:clients=dict(c.execute('SELECT name,seen_at FROM clients'))
            team=json.loads((Path(__file__).parent/'agents/roles.json').read_text())
            live=self.live.status();ozon_state='not_authorized' if not(live['orders']['available'] or live['stock']['available']) else 'scope_review_required' if not live['orders_scope_confirmed'] else 'readonly_connected' if live['orders']['fresh'] and live['stock']['fresh'] else 'partial_or_stale'
            platform_states=self.platforms.summary()
            return {'version':'0.1.0','mode':'read_only' if ozon_state!='not_authorized' or any(s['fresh_resources']for s in platform_states.values()) else 'unconfigured','platforms':[{'id':p,'name':LABELS[p],**({'status':ozon_state}if p=='ozon'else platform_states[p])}for p in PLATFORMS], 'clients':clients,'knowledge':{'configured':self.root()is not None,'notes':len(self.notes())},'marketplace_writes':False,'live_connection':live,'agent_team':{'roles':team['roles'],'deployment':team['deployment'],'default_role':team['default_role']}}
        if name=='commerce_task_create':
            role=args.get('input',{}).get('agent_role')
            if role is not None:
                team=json.loads((Path(__file__).parent/'agents/roles.json').read_text())
                if role not in [v for r in team['roles']for v in [r['id'],*r.get('legacy_ids',[])]]:raise ValueError('unknown_agent_role')
        if name.startswith('commerce_task_'):return self.core.invoke(name,args)
        if name in ('commerce_unit_economics','commerce_restock_plan'):
            result=(unit_economics if name=='commerce_unit_economics' else restock_plan)(args['input'])
            result['evidence']={'input':args['input'],'input_sha256':digest(canonical(args['input'])),'calculated_at':now(),'model_version':'operations-v1','tool':name,'verification':'caller_input_not_independently_verified'}
            result['result_sha256']=digest(canonical(result))
            return result
        if name=='commerce_collection_template':return collection_template(args['platform'])
        if name=='commerce_collection_check':return collection_check(args['record'])
        if name=='commerce_collection_export':return collection_export(args['record'],args.get('final',False))
        if name=='commerce_translation_start':return self.translations.start(args['input'],args['idempotency_key'])
        if name=='commerce_translation_get':return self.translations.get(args['job_id'])
        demo=args.get('demo',False);platform=args.get('platform','all');store=args.get('store_id','all');market=args.get('market','all')
        if not demo and name in ('commerce_dashboard','commerce_orders_list','commerce_products_list'):return self.live.workbench(name,args)
        selected=[i for i,p in enumerate(PLATFORMS)if platform in ['all',p]and store in ['all',p+'-demo']and market in ['all',MARKETS[p]]]
        if name=='commerce_dashboard':
            rows=[{'id':PLATFORMS[i],'name':LABELS[PLATFORMS[i]],'amount':SALES[i]}for i in selected] if demo else []
            amount=sum(x['amount']for x in rows)
            indices=selected
            return {'mode':'demo' if demo else 'live','currency':'USD','timezone':'Asia/Shanghai','rate_note':'模拟汇率与数据，不用于经营决策'if demo else'尚未授权店铺，暂无汇率与经营数据','sales':amount if demo else None,'orders':sum([392,348,286,180,78][i]for i in indices)if demo else None,'pending':sum([8,12,4,5,3][i]for i in indices)if demo else None,'stock_alerts':sum([3,1,1,1,1][i]for i in indices)if demo else None,'platforms':rows,'updated_at':now(),'data_source':'synthetic'if demo else'not_connected'}
        if name=='commerce_orders_list':
            data=[{'id':f'SIM-{1001+i}','platform':p,'store_id':p+'-demo','store':'示例店铺','market':MARKETS[p],'product':['宠物梳理套装','便携咖啡杯','桌面收纳架','旅行收纳套装','硅胶厨房工具'][i],'sku':['PET-021','CUP-014','HOME-008','BAG-006','KIT-031'][i],'amount':[8990,79,129,1490,36][i],'currency':['RUB','USD','USD','MXN','USD'][i],'status':['待发货','物流异常','运输中','待处理','待确认'][i]}for i,p in enumerate(PLATFORMS)if i in selected]if demo else[]
            data=[x for x in data if(not args.get('status')or x['status']==args['status'])and args.get('query','').lower()in json.dumps(x,ensure_ascii=False).lower()]
            return {'mode':'demo'if demo else'live','orders':data,'total':len(data),'data_source':'synthetic'if demo else'not_connected'}
        if name=='commerce_products_list':
            orders=self.invoke('commerce_orders_list',{'demo':demo,'platform':platform,'store_id':store,'market':market},client)['orders']
            return {'mode':'demo'if demo else'live','products':[{'sku':o['sku'],'name':o['product'],'platform':o['platform'],'available':[3,26,52,12,7][PLATFORMS.index(o['platform'])],'threshold':10,'currency':o['currency'],'price':o['amount']}for o in orders]}
        if name=='commerce_reports_list':
            with self.core.db() as c:
                rows=c.execute('SELECT r.id,r.mode,r.content,r.created_at,s.scope FROM reports r LEFT JOIN report_scopes s ON s.report_id=r.id ORDER BY r.rowid DESC LIMIT 30').fetchall()
            return {'reports':[self.workflow.present(r[:4],json.loads(r[4]) if r[4] else None) for r in rows]}
        if name=='commerce_knowledge_list':return {'configured':self.root()is not None,'notes':self.notes()}
        if name=='commerce_knowledge_read':
            content=read_note(self.safe_note(args['path']));return {'path':args['path'],'content':content.decode('utf-8'),'sha256':hashlib.sha256(content).hexdigest()}
        if name=='commerce_knowledge_search':
            q=args['query'].strip().lower()
            if not q:raise ValueError('query_required')
            documents=[]
            for note in self.notes():
                try:content=read_note(self.safe_note(note)).decode('utf-8')
                except UnicodeError:continue
                documents.append({'path':note,'content':content})
            return {'hits':ranked_notes(documents,q),'configured':self.root()is not None}
        if name=='commerce_summary_save':
            root=self.root()
            if root is None:raise ValueError('knowledge_not_configured')
            report_id=args['report_id']
            if not re.fullmatch('[a-f0-9]{20}',report_id):raise ValueError('invalid_report_id')
            with self.core.db() as c:row=c.execute('SELECT * FROM reports WHERE id=?',(report_id,)).fetchone()
            if row is None:raise ValueError('report_not_found')
            name='运营简报-'+report_id+'.md';target=root/name
            if target.is_symlink():raise ValueError('invalid_note_path')
            try:
                with target.open('x',encoding='utf-8') as f:f.write(row[3])
            except FileExistsError:
                if target.read_text()!=row[3]:raise ValueError('note_conflict')
            return {'saved':True,'path':name,'mode':row[2]}
        raise ValueError('unknown_tool')
