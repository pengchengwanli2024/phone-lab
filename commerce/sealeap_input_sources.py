"""Reviewed source selectors for previously unresolved inputs, never invented fields."""
import hashlib
import re

# Select actual workflow prerequisites or dedicated reference contracts.
# These candidates still need domain review and do not claim complete schemas.
WORKFLOW_HEADINGS={
 'sealeap-amazon-acos-diagnostics':['2. 锁定分析作用域'],
 'sealeap-amazon-ad-architecture':['1. 固定对象和目标'],
 'sealeap-amazon-ca-apparel-ads':['1. 锁定对象、目标和双时间轴'],
 'sealeap-amazon-consumer-electronics-category-growth':['1. 分类与作用域','3. 技术事实闸门'],
 'sealeap-amazon-eu-amc-audience':['1. 锁定问题、主体与站点'],
 'sealeap-amazon-eu-multimarket-ads':['1. 建立站点 × ASIN 资格矩阵'],
 'sealeap-amazon-fashion-category-growth':['1. 固定站点与细分类目'],
 'sealeap-amazon-full-funnel-growth':['1. 锁定问题与作用域'],
 'sealeap-amazon-global-growth-planning':['1. 固定业务结果','2. 画当前流程'],
 'sealeap-amazon-home-lifestyle-category-growth':['1. 固定细分类目与站点'],
 'sealeap-amazon-jp-apparel-ads':['1. 锁定投放对象'],
 'sealeap-amazon-listing-optimizer':['1. 锁定对象、目标和基线'],
 'sealeap-amazon-localization-marketing':['1. 固定源与目标'],
 'sealeap-amazon-prime-day-planning':['1. 锁定当前事件'],
 'sealeap-amazon-product-targeting':['1. 锁定对象、目标和基线'],
 'sealeap-amazon-sp-video-ads':['1. 确认作用域与资格'],
 'sealeap-amazon-uk-apparel-ads':['1. 锁定投放对象'],
 'sealeap-amazon-sp-offsite-diagnostics':['先取这些资料']}
REFERENCES={
 'sealeap-amazon-apparel-lifecycle-ads':('references/output-contract.md',['1. 对象与授权范围','2. 数据包与完整性']),
 'sealeap-apollo-ad-planning':('references/economics-input.md',['经济输入']),
 'sealeap-apollo-asin-research-brief':('references/report-input.md',['报告数据包']),
 'sealeap-apollo-batch-title-rewrite':('references/title-input.md',['标题检查输入']),
 'sealeap-apollo-competitor-monitor':('references/snapshot-input.md',['快照输入']),
 'sealeap-apollo-price-discounts':('references/discount-input.md',['折扣计划输入']),
 'sealeap-apollo-product-research':('references/report-input.md',['报告数据包']),
 'sealeap-amazon-creator-commission-planning':('references/input-contract.md',['加佣测算输入']),
 'sealeap-amazon-data-kiosk-reconciliation':('references/data-contract.md',['数据与对账契约']),
 'sealeap-amazon-first-party-audience':('references/data-readiness.md',['第一方数据准备与试验']),
 'sealeap-amazon-ppwr-packaging-audit':('references/country-checklist.md',['国家、主体与材料核对表'])}
WORKFLOW_STEPS={
 'sealeap-apollo-ads-demo':('执行流程','1.'),
 'sealeap-apollo-keyword-library':('执行流程','1.'),
 'sealeap-amazon-ads-mcp-analytics':('工作流','2.'),
 'sealeap-amazon-multichannel-operations':('工作流','1.'),
 'sealeap-amazon-support-case-tracking':('工作流','1.')}


def block(lines,heading):
    matches=[i for i,line in enumerate(lines) if re.sub(r'^#{1,6}\s+','',line)==heading and re.match(r'^#{1,6}\s+',line)]
    if len(matches)!=1:raise ValueError('sealeap_input_source_heading_changed')
    start=matches[0]+1;end=next((i for i in range(start,len(lines)) if re.match(r'^#{1,6}\s+',lines[i])),len(lines))
    return start,end


def fragments(lines,start,end):
    """Keep paragraphs and list items, including tables; never consume examples."""
    current=[];begin=start
    for i in range(start,end):
        line=lines[i]
        if re.match(r'^(?:示例结构|```|脚本拒绝|输出 DRAFT|PASS 仅表示)',line):break
        is_list=bool(re.match(r'^\s*(?:[-*+]\s+|\d+[.)]\s+)',line))
        if not line.strip() or is_list:
            if current:yield begin,current;current=[]
        if line.strip():
            if not current:begin=i
            current.append(line)
    if current:yield begin,current


def resolve(entry,reader):
    """reader accepts only registered source files and returns exact UTF-8 text."""
    registered={f['path']:f for f in entry['files']};cache={}
    def read(path):
        if path not in registered:raise ValueError('sealeap_input_reference_not_registered')
        if path not in cache:
            text=reader(path)
            if hashlib.sha256(text.encode()).hexdigest()!=registered[path]['sha256']:raise ValueError('sealeap_input_reference_hash_changed')
            cache[path]=text.splitlines()
        return cache[path]
    def items(path,heading,selector=None):
        lines=read(path);start,end=block(lines,heading)
        if selector:
            selected=[i for i in range(start,end) if lines[i].startswith(selector)]
            if len(selected)!=1:raise ValueError('sealeap_input_workflow_step_changed')
            pairs=[(selected[0],[lines[selected[0]]])]
        else:pairs=list(fragments(lines,start,end))
        return [dict(text='\n'.join(text),source=dict(path=path,file_sha256=registered[path]['sha256'],heading=heading,file_line_start=i+1,file_line_end=i+len(text)),classification='source_prerequisite_candidate_requires_review') for i,text in pairs]
    common=[];modes={};ident=entry['id']
    for heading in WORKFLOW_HEADINGS.get(ident,[]):common+=items('SKILL.md',heading)
    if ident in REFERENCES:
        path,headings=REFERENCES[ident]
        for heading in headings:common+=items(path,heading)
    if ident in WORKFLOW_STEPS:
        heading,prefix=WORKFLOW_STEPS[ident];common+=items('SKILL.md',heading,prefix)
    for mode in entry.get('subcapabilities',[]):
        path=mode['reference'];lines=read(path)
        if mode['name']=='sealeap-athena-find-skills':
            selected=[i for i,line in enumerate(lines) if '先从用户问题提取平台、任务和只读/写入要求' in line]
            if len(selected)!=1:raise ValueError('sealeap_local_search_inputs_changed')
            i=selected[0];inputs=[dict(text=lines[i],source=dict(path=path,file_sha256=registered[path]['sha256'],heading='本地技能与旧名称检索',file_line_start=i+1,file_line_end=i+1),classification='source_prerequisite_candidate_requires_review')]
            common+=inputs
        else:
            start,end=block(lines,'必要输入');fields=[i for i in range(start,end) if lines[i].strip()]
            if len(fields)!=2 or not lines[fields[1]].startswith('从当前会话'):raise ValueError('sealeap_mode_input_shape_changed')
            i=fields[0];inputs=[dict(text=lines[i],source=dict(path=path,file_sha256=registered[path]['sha256'],heading='必要输入',file_line_start=i+1,file_line_end=i+1),classification='selected_mode_input_candidate_requires_review')]
        deliveries=items(path,'交付')
        for kind,prefix,rows in [('inputs','MI',inputs),('deliverables','MD',deliveries)]:
            for i,row in enumerate(rows,1):row.update(id=prefix+str(i),kind=kind,mode_id=mode['name'])
        modes[mode['name']]=dict(mode_id=mode['name'],reference=path,inputs=inputs,deliverables=deliveries)
    # The local search has a single common query requirement, not 226 business routes.
    return dict(common=common,modes=modes,mode_selection_required=bool(modes) and ident!='sealeap-athena-find-skills')
