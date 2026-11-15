import type { Plan } from './adoption-types';
export function connectionError(plan:Plan, from:string, to:string):string {
  const ids=new Set(plan.steps.map(s=>s.id));
  if(!ids.has(from)||!ids.has(to))return '请选择有效的前后步骤。';
  if(from===to)return '步骤不能依赖自己。';
  if(plan.graph.edges.some(e=>e.from===from&&e.to===to))return '这条依赖已存在。';
  const links=new Map([...ids].map(id=>[id,[] as string[]]));
  for(const edge of plan.graph.edges)links.get(edge.from)?.push(edge.to);
  const seen=new Set<string>(),queue=[to];
  while(queue.length){const current=queue.pop()!;if(current===from)return '这条依赖会形成循环。';if(seen.has(current))continue;seen.add(current);queue.push(...(links.get(current)||[]));}
  return '';
}
export function removeStep(plan:Plan,id:string):Plan {
  const positions={...plan.graph.positions};delete positions[id];
  return {...plan,steps:plan.steps.filter(s=>s.id!==id),graph:{positions,edges:plan.graph.edges.filter(e=>e.from!==id&&e.to!==id)}};
}
