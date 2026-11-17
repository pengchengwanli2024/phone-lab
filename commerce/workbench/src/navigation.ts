/** Business destinations are flat; old routes remain addressable within them. */
export function initialDestination(search: URLSearchParams, hash = ''): string {
  return search.get('tab') || (hash === '#social' ? 'intelligence' : 'overview');
}
export const labels: Record<string, string> = {
  listing:'上架准备', 'store-ops':'日常运营', overview: '运营台', workspace: '商品工作区', orders: '订单', products: '库存', operations: '成本与定价',
  agent: '模型分析', exposure: '经营关联', platforms: '平台数据', pilots: '商品候选', live: 'Ozon 经营', 'order-imports': '订单导入', workflow: '工作流画布', memory: '资料与知识',
  alerts: '经营提醒', research: '研究资料', creative: '创意工作室', skills: '技能', intelligence: '全球情报',
  insights: '选品与评论', support: '客服', organization: '岗位交接', tasks: '任务中心', connections: '连接与授权', models: '模型管理', restock: '补货计划', phones: '手机墙', 'assistant-team': '智能体团队', 'operating-control':'自动经营', tools:'工具发现',
};
export const storeSections = [
  {id:'daily',label:'经营与提醒',defaultRoute:'store-ops',primary:['store-ops','alerts'],secondary:[]},
  {id:'catalog',label:'商品与上架',defaultRoute:'workspace',primary:['workspace','pilots','listing'],secondary:['research','insights','operations','workflow']},
  {id:'fulfillment',label:'订单与客服',defaultRoute:'orders',primary:['orders','order-imports','support'],secondary:[]},
  {id:'inventory',label:'库存与补货',defaultRoute:'products',primary:['products','restock'],secondary:[]},
  {id:'connections',label:'店铺连接',defaultRoute:'platforms',primary:['platforms','live'],secondary:[]},
];
export const storeSectionFor = (route:string) => storeSections.find(section=>[...section.primary,...section.secondary].includes(route.replace('old:','')));
export const navigation: { id: string; label: string; icon: string; items: string[] }[] = [
  { id: 'overview', label: '运营台', icon: 'grid', items: ['overview'] },
  { id: 'store-ops', label: '店铺管理', icon: 'store', items: storeSections.flatMap(section=>[...section.primary,...section.secondary]) },
  { id: 'creative', label: '内容', icon: 'image', items: ['creative'] },
  { id: 'intelligence', label: '情报', icon: 'book', items: ['intelligence', 'exposure'] },
  { id: 'tasks', label: '任务', icon: 'clock', items: ['tasks', 'organization', 'agent'] },
  { id: 'skills', label: '能力与设置', icon: 'bolt', items: ['skills', 'tools', 'operating-control', 'assistant-team', 'models', 'connections', 'memory', 'phones'] },
];
export const destinationFor = (route: string) => navigation.find(destination => destination.items.includes(route.replace('old:', '')));
/** Destination labels do not rename stored conversation or form-draft scopes. */
export const businessModule = (route: string) => {
  const leaf = route.replace('old:', '');
  return leaf==='phones'?'intelligence':['models','memory','assistant-team','operating-control','tools'].includes(leaf) ? 'connections' : ['store-ops','order-imports'].includes(leaf) ? 'orders' : leaf === 'restock' ? 'operations' : ['workspace','workflow','listing'].includes(leaf) ? 'organization' : leaf;
};

/** Restore the saved business page without guessing another case's selection. */
export function conversationDestination(context: { module: string; entity?: { kind: string; id: string } }, pageContext?: unknown): string {
  const caseBound = context.module === 'organization' && context.entity?.kind === 'case';
  const page = pageContext && typeof pageContext === 'object' && 'page' in pageContext ? pageContext.page : null;
  if (typeof page === 'string' && labels[page] && businessModule(page) === context.module
    && (!['workspace', 'listing', 'workflow'].includes(page) || caseBound)) return page;
  return caseBound ? 'workspace' : context.module;
}
