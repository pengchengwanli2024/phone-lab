"""Host independent tool contracts and deliberately small declarative surface."""
KINDS=('skill','plugin','agent','workflow')
SAFE_BUILTINS={
    'commerce_runtime_status':None,'commerce_model_list':None,
    'commerce_unit_economics':None,'commerce_restock_plan':None,'commerce_packing_estimate':None,
    'commerce_organization_board':'case_id','commerce_organization_brief':'case_id',
    'commerce_media_overview':'project_id',
    'commerce_media_readiness':'project_id',
    'commerce_media_provider_catalog':None,'commerce_media_provider_get':'media_job',
    'commerce_media_provider_generate':'media_request',
    'commerce_media_request_execute':'media_request','commerce_media_request_get':'media_request_read',
    'commerce_media_request_create':'media_project',
}
PROTECTED_BUILTINS={'commerce_media_provider_generate','commerce_media_request_execute','commerce_media_request_create'}
DEFAULT_LIMITS={'max_steps':32,'max_model_calls':8,'max_seconds':300,'max_output_bytes':64000}
HARD_LIMITS={'max_steps':100,'max_model_calls':20,'max_seconds':86400,'max_output_bytes':128000}

def definitions(schema,string):
    obj={'type':'object'};ext={'extension_id':string};run={'run_id':string};version={'expected_version':{'type':'integer','minimum':1}};revision={'expected_revision':{'type':'integer','minimum':1}}
    launch={**ext,'input':obj,'scope':obj,'budget':obj,'idempotency_key':string}
    rows=[
        ('assist','通过已配置模型起草声明式扩展；生成后待人工保存测试启用',{'kind':{'type':'string','enum':list(KINDS)},'instructions':{'type':'string','minLength':1,'maxLength':12000},'model_id':string,'idempotency_key':string,'budget':obj},['kind','instructions','idempotency_key']),
        ('list','读取本地扩展注册表与版本状态',{'kind':{'type':'string','enum':list(KINDS)}},[]),
        ('get','读取指定扩展版本和来源',dict(ext,version={'type':'integer','minimum':1}),['extension_id']),
        ('capabilities','读取受控能力、定义模板、预算及映射语法',{},[]),
        ('save','创建或编辑声明式扩展新版本；编辑会停用旧版本',{'definition':obj,**version},['definition']),
        ('import','从显式 JSON 文档导入声明式扩展；内容不获得执行权限',{'document':{'type':'string','maxLength':64000},'provenance':obj,**version},['document','provenance']),
        ('test','创建只读测试；模型及外部写入只做结构验证并明确标记',launch,['extension_id','idempotency_key']),
        ('enable','启停当前已测试版本；停用撤销未完成运行',dict(ext,**version,enabled={'type':'boolean'}),['extension_id','expected_version','enabled']),
        ('rollback','复制历史版本为新版本；须重新测试启用',dict(ext,**version,target_version={'type':'integer','minimum':1}),['extension_id','expected_version','target_version']),
        ('run','按当前启用版本与依赖创建持久任务；入队不表示完成',launch,['extension_id','idempotency_key']),
        ('run_get','读取任务进度、检查点、审批、真实结果和来源',run,['run_id']),
        ('run_list','读取最近扩展运行',ext,[]),
        ('run_cancel','取消排队或执行中的扩展运行',run,['run_id']),
        ('run_resume','从安全检查点恢复中断或预算内失败任务；不重发未知操作',run,['run_id']),
        ('run_approve','对绑定运行、步骤及输入哈希的单次能力作显式审批',dict(run,step_id=string,input_sha256={'type':'string','pattern':'^[a-f0-9]{64}$'},decision={'type':'string','enum':['approve','reject']}),['run_id','step_id','input_sha256','decision']),
        ('schedule_save','保存手动、间隔、条件或运行后触发计划；默认停用',{'schedule':obj,**revision},['schedule']),
        ('schedule_run','按已保存范围和预算手动触发已启用计划；按幂等键去重',{'schedule_id':string,**revision,'idempotency_key':string},['schedule_id','expected_revision','idempotency_key']),
        ('schedule_list','读取持久化自动化计划',ext,[]),
        ('schedule_enable','启停指定计划版本',{'schedule_id':string,**revision,'enabled':{'type':'boolean'}},['schedule_id','expected_revision','enabled']),
    ]
    return [('commerce_extension_'+name,description,schema(properties,required)) for name,description,properties,required in rows]

def templates():
    return [
        {'kind':'skill','name':'本机状态只读技能','spec':{'steps':[{'id':'status','uses':{'builtin':'commerce_runtime_status'}}],'output':{'$ref':'steps.status'}}},
        {'kind':'plugin','name':'本机只读工具插件','spec':{'transport':'builtin','tool':'commerce_runtime_status','effect':'read'}},
        {'kind':'agent','name':'范围内分析助手','spec':{'model_id':'project-default','instructions':'依据输入和已授权工具结果回答；缺失证据应明确说明。','tools':[],'max_turns':4}},
        {'kind':'workflow','name':'本机状态工作流','spec':{'steps':[{'id':'status','uses':{'builtin':'commerce_runtime_status'}}],'output':{'$ref':'steps.status'}}},
    ]
