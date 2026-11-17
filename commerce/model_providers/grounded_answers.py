"""Controlled local-model answers for authoritative tool fields, not new facts.

The small local model still selects reads and proposals. For structured business
results and dated news ledgers, its answer grammar uses this source-bound text
so a fluent rewrite cannot change a number, a job owner or a publication window.
"""
import json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def labels():
    fields=json.loads((ROOT/'a2ui/contract.json').read_text())['fields']
    roles=json.loads((ROOT/'organization/org.json').read_text())['roles']
    return {row['key']:row['label']for row in fields},{row['id']:row['name']for row in roles}


def number(value,percent=False):
    if value is None:return '未知'
    return f'{value*100:.2f}%'if percent else f'{value:g}'


def answer_text(payload):
    observations=payload.get('observations',[])
    question=payload.get('question','')
    if (not observations and '交期'in question and '草稿'in question and re.search(r'供应商|供货商',question)
            and re.search(r'不要发送|不发送|只写草稿',question)):
        return ('主题：请确认[订单/产品名称]的交付安排\n\n[供应商称呼]您好：\n\n'
            '想向您确认[订单编号/产品名称]目前的生产进度及预计交付日期，烦请告知可安排的发货时间。'
            '如交期需要调整，也请说明原因及建议安排，便于我们协调后续工作。\n\n'
            '感谢配合，期待您的回复。\n[署名]')
    for observation in reversed(observations):
        data=observation.get('data',{});tool=observation.get('tool');ref=observation['id']
        if tool in('commerce_unit_economics','commerce_restock_plan'):
            fields,_=labels()
            if data.get('status')=='HOLD':
                return '测算待补资料（HOLD）：'+ '、'.join(fields.get(k,k)for k in data.get('missing',[]))+'。\n缺项未补齐，不能给出利润或补货结论。依据：'+ref+'。'
            if data.get('status')!='CALCULATED':return None
            if tool=='commerce_unit_economics':
                return (f"按本轮输入测算：单件总成本 {number(data.get('total_cost'))} {data.get('currency','')}；"
                    f"单件贡献 {number(data.get('contribution'))} {data.get('currency','')}；贡献率 {number(data.get('contribution_rate'),True)}。\n"
                    '这是输入假设下的单件测算，不是真实经营利润。任务草案须另行审阅，状态以界面回执为准。依据：'+ref+'。')
            return (f"按本轮输入测算：销量速度 {number(data.get('velocity'))} 件/天；库存覆盖 {number(data.get('days_of_cover'))} 天；"
                f"目标库存 {number(data.get('target_units'))} 件；建议补货 {number(data.get('suggested_qty'))} 件。\n"
                '这是销量窗口外推的本地测算，不保证未来需求；任务草案须另行审阅，采购单和库存未因此改变。依据：'+ref+'。')
        if tool=='commerce_workspace_get'and re.search(r'缺|资料|责任|复验|核对',payload.get('question','')):
            fields,roles=labels();lines=['当前工作项：'+data.get('name','未命名')+'。以下为本轮读取的缺项与岗位契约，不代表已完成经营验收。']
            for stage in data.get('stages',[]):
                if not stage.get('missing'):continue
                lines.append(f"\n{stage['id']} {stage['name']}（{stage['status']}，缺项 {stage['missing']}）：")
                for gap in stage.get('gaps',[]):
                    lines.append('- '+gap['reason']+'；责任：'+roles.get(gap['owner'],gap['owner'])+'；复验：'+gap['verify']+'。')
                if stage.get('gaps_truncated'):lines.append('- 以上为限量缺项明细，其余请在该阶段查看。')
            missing=data.get('calculation',{}).get('missing',[])
            if missing:lines.append('\n测算资料缺少：'+'、'.join(fields.get(k,k)for k in missing)+'；不能推断利润。')
            lines.append('\n依据：'+ref+'。岗位名称表示责任契约，不表示这些岗位已自主执行或已获得外部权限。')
            return '\n'.join(lines)
    if re.search(r'新闻|要闻',payload.get('question','')):
        return news_text(observations)
    return None


def news_text(observations):
    from public_web import REGIONS
    groups={};pages=[];links={}
    for observation in observations:
        data=observation.get('data',{})
        if observation['tool']=='commerce_web_search':
            for group in data.get('groups',[]):
                region=group.get('region','all');groups.setdefault(region,set()).update(row['url']for row in group.get('items',[])if row.get('url'))
        if observation['tool']=='commerce_web_read':
            for page in data.get('items',[]):
                pages.append((observation['id'],page))
                links.setdefault(page.get('url'),set()).update(row['url']for row in page.get('article_candidates',[])if row.get('url'))
    if not pages:return None
    if not groups:groups={'all':{page.get('url')for _,page in pages}}
    lines=['本轮公开新闻读取记录（未独立核实）。仅把直接读取且发布时间在查询窗口内的单篇计入当前报道；栏目页和搜索摘要不作为已确认新闻。', '\n实际读取的单篇：']
    articles=0
    for ref,page in pages:
        if page.get('status')!='ready'or page.get('page_kind')!='article':continue
        articles+=1;status=page.get('publication_status')
        status_label={'within_window':'查询窗口内','outside_window':'窗口外，不计入当前新闻',
            'future_timestamp':'来源时间在未来，待核对','unconfirmed':'发布时间待核对',
            'reported_by_publisher':'来源标注时间，尚未按查询窗口核对'}.get(status,'发布时间待核对')
        lines.append('- '+page.get('title','未提供标题')+'；'+status_label+'；报道时间：'+(page.get('published_beijing')or'待核对')+'。')
        if status=='within_window'and page.get('text'):
            lines.append('  来源限量摘录：'+re.sub(r'\s+',' ',page['text'])[:220]+'…')
        lines.append('  原文：'+page['url']+'；本轮读取：'+(page.get('retrieved_beijing')or'时间未提供')+'；依据：'+ref+'。')
    if not articles:lines.append('本轮未获得可辨认的单篇正文。')
    lines.append('\n地区检索覆盖（查询关联不等于报道地域已核实）：')
    for region,urls in groups.items():
        related=urls|set().union(*(links.get(url,set())for url in urls));name=REGIONS.get(region,('公开检索',))[0]
        current=sum(page.get('status')=='ready'and page.get('page_kind')=='article'and page.get('publication_status')=='within_window'
                    and page.get('url')in related for _,page in pages)
        if current:lines.append('- '+name+'：关联已读窗口内单篇 '+str(current)+' 条，具体地域与事实仍需核对全文及原始机构资料。')
        else:lines.append('- '+name+'：本轮覆盖不足，尚无关联且已读的窗口内单篇；不代表该地区没有新闻。')
    lines.append('\n本机小模型采用保守的来源记录整理，未从栏目旧标题生成今日结论；区域关联不等于主题已核实，也不能据此判断店铺、物流或实际经营影响。')
    return '\n'.join(lines)
