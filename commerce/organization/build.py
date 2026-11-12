"""Generate role cards and the legacy-compatible role catalogue from org.json."""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parent
def products():
    contract=json.loads((ROOT/'org.json').read_text());out={}
    for role in contract['roles']:
        stages=[s for s in contract['stages'] if s['role']==role['id']]
        out[ROOT/'roles'/f"{role['id']}.md"]=f"""# {role['name']} · {role['id']}

身份与范围：仅处理工作项指定的平台、市场、SKU、币种和证据版本；角色配置不代表模型正在运行。

使命：{role['mission']}。

触发：对应门禁有缺项，或收到绑定工作项与证据版本的本地交接任务。

输入契约：工作项范围、上游产物、原文与中文说明、来源时间和 SHA-256；未知值不得改成零。

能力包：{', '.join(role['skill_pod']['tools'])}。只在已有授权和真实工具可用范围内执行。

交付物：{', '.join(s['id']+' '+s['artifact_kind'] for s in stages) or '岗位简报与缺项交接任务'}；保留原始输入和中文字段说明。

判据：重新运行对应检查，来源和哈希仍然匹配；任务被标记完成不能直接关闭门禁。

阻断权：发现缺项、来源变更、范围错配或回执未知时停止当前交接，并注明缺什么、谁补、补完如何验。没有批准或扩大外部权限的权力。

失败模式：FAIL 交回产物岗位修复；BLOCKED 交接到能力或接入责任岗位；HOLD 保留草稿并补资料。禁止把本地模板或合成样本说成真实经营结果。

交接：输入与产物必须绑定相同工作项；素材真正交付到本机工作项目录后，还须重新验证交付文件。

指标：当前可验证产物、未解决缺项、交接证据完整性；不从门禁通过率推断转化或销量。
"""
    old=json.loads((ROOT.parent/'agents/roles.json').read_text())
    old.update(schema='commerce-agent-team-v2',source='organization/org.json',default_role=contract['default_role'],roles=[dict(id=r['id'],name=r['name'],responsibility=r['mission'],scope='explicit-work-item',allowed=r['allowed'],state=r['state'],legacy_ids=r['legacy_ids'])for r in contract['roles']])
    out[ROOT.parent/'agents/roles.json']=json.dumps(old,ensure_ascii=False,indent=2)+'\n'
    return out
if __name__=='__main__':
    check='--check'in sys.argv;drift=[]
    for path,content in products().items():
        if check:
            if not path.exists()or path.read_text()!=content:drift.append(path.name)
        else:path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content)
    if drift:raise SystemExit('Organization generated files differ: '+', '.join(drift))
    print('Organization contracts and role cards match.'if check else'Organization role cards generated.')
