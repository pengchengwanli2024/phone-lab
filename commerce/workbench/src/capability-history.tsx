import { useEffect, useRef, useState } from 'react';
import { api, errorText } from './api';
import { Badge, Button, Empty, ErrorNotice, Panel } from './ui';
import { historyRows, timeText, type LibrarySource, type MemoryRecord, type SkillCase } from './capability-history-state';
import { ImprovementCandidates } from './improvement-candidates';
import './adoption.css';

interface Loaded { items: MemoryRecord[] | null; truncated: boolean; cases: SkillCase[] | null; sources: LibrarySource[] | null; total: number | null; errors: string[] }

/** Read-only. It lists what the existing stores already recorded and performs no write, model call or retry. */
export function CapabilityHistory({ demo }: { demo: boolean }) {
  const [data, setData] = useState<Loaded | null>(null), [loading, setLoading] = useState(true);
  const generation = useRef(0);
  async function load() {
    const request = ++generation.current; setLoading(true);
    const [memory, cases, status] = await Promise.allSettled([
      api<{ items: MemoryRecord[]; truncated: boolean }>('commerce_memory_list', { synthetic: demo }),
      api<{ cases: SkillCase[] }>('commerce_skills_cases'),
      api<{ total: number; sources: LibrarySource[] }>('commerce_skills_status'),
    ]);
    if (request !== generation.current) return;
    const errors: string[] = [];
    const failed = (name: string, result: PromiseSettledResult<unknown>) => { if (result.status === 'rejected') errors.push(`${name}未读到：${errorText(result.reason)}`); };
    failed('事实与摘要', memory); failed('技能任务', cases); failed('能力库版本', status);
    setData({
      items: memory.status === 'fulfilled' ? memory.value.items : null, truncated: memory.status === 'fulfilled' && memory.value.truncated,
      cases: cases.status === 'fulfilled' ? cases.value.cases : null,
      sources: status.status === 'fulfilled' ? status.value.sources : null, total: status.status === 'fulfilled' ? status.value.total : null, errors,
    });
    setLoading(false);
  }
  useEffect(() => { setData(null); void load(); return () => { generation.current++; }; }, [demo]);
  const rows = data ? historyRows(data.items || [], data.cases || [], demo) : [];
  return <div>
    <p className="adoption-notice">{demo ? '合成验证范围' : '本机资料范围'} · 只读。这里按建立时间列出已有的事实、摘要和技能任务记录；确认或撤回发生的时间没有单独记录，以修订号为准。改进候选来自真实运行中重复出现的失败，见下方；基线与候选评估、版本回滚目前没有记录来源，此处不展示。</p>
    {data?.errors.map(text => <ErrorNotice key={text}>{text}</ErrorNotice>)}
    <Panel title="能力库版本">{data?.sources ? <ul className="adoption-list">{data.sources.map(source => <li className="adoption-item" key={source.id}>
      <p><strong>{source.id}</strong> · {source.skills} 项技能</p><p className="adoption-scope">固定版本 {source.commit.slice(0, 12)}</p>
    </li>)}{data.total !== null && <li className="adoption-scope">已登记 {data.total} 项；已读取源码不等于业务验证。</li>}</ul> : <Empty>{loading ? '正在读取能力库版本…' : '能力库版本未读到。'}</Empty>}</Panel>
    <ImprovementCandidates />
    <Panel title="进化记录" action={<Button disabled={loading} onClick={() => void load()}>刷新</Button>}>
      {rows.length ? <ul className="adoption-list">{rows.map(row => <li className="adoption-item" key={row.key}>
        <div className="adoption-actions"><Badge>{row.label}</Badge><Badge tone={row.tone}>{row.status}</Badge></div>
        <p>{row.title}</p><p className="adoption-scope">{timeText(row.at)} · {row.meta.join(' · ')}</p>
      </li>)}</ul> : <Empty>{loading ? '正在读取记录…' : data?.errors.length ? '记录未读全，见上方提示。' : '当前范围尚无事实、摘要或技能任务记录。'}</Empty>}
      {data?.truncated && <p className="adoption-scope">事实与摘要超过 500 条，仅显示最近 500 条。</p>}
      {data?.cases && <p className="adoption-scope">技能任务只读取最近 30 条，并只显示属于当前范围的记录。</p>}
    </Panel>
  </div>;
}
