/** Business destinations are flat; old routes remain addressable within them. */
export function initialDestination(search: URLSearchParams, hash = ''): string {
  return search.get('tab') || (hash === '#social' ? 'intelligence' : 'overview');
}
export const labels: Record<string, string> = {
  listing:'上架准备', pipeline:'商品管线看板', decisions:'经营决策检查', 'store-ops':'日常运营', overview: '运营台', workspace: '商品工作区', orders: '订单', products: '库存', operations: '成本与定价',
  agent: '模型分析', exposure: '经营关联', platforms: '平台数据', pilots: '商品候选', live: 'Ozon 经营', 'order-imports': '订单导入', workflow: '工作流画布', memory: '资料与知识',
  alerts: '经营提醒', research: '研究资料', creative: '创意工作室', skills: '技能', intelligence: '全球情报',
  insights: '选品与评论', support: '客服', organization: '岗位交接', tasks: '任务中心', connections: '连接与授权', models: '模型管理', restock: '补货计划', phones: '手机墙', 'assistant-team': '智能体团队', 'operating-control':'自动经营', tools:'工具发现',
};
export interface NavigationSection {id:string;label:string;defaultRoute:string;primary:string[];secondary:string[]}
/**
 * Six work surfaces organised by who is doing what. A destination id is also the
 * route opened when it is selected. Leaf routes, deep links, conversation scopes
 * and form-draft scopes are unchanged; only the grouping moved.
 */
const pipelineSections: NavigationSection[] = [
  {id:'discovery',label:'选品与研究',defaultRoute:'pipeline',primary:['pipeline','pilots','research','insights','decisions'],secondary:[]},
  {id:'product',label:'商品与成本',defaultRoute:'workspace',primary:['workspace','operations','workflow'],secondary:[]},
  {id:'launch',label:'内容与上架',defaultRoute:'listing',primary:['creative','listing'],secondary:[]},
];
/** Daily store operations; product preparation lives in the product pipeline. */
export const storeSections: NavigationSection[] = [
  {id:'daily',label:'经营与提醒',defaultRoute:'store-ops',primary:['store-ops','alerts'],secondary:[]},
  {id:'fulfillment',label:'订单与客服',defaultRoute:'orders',primary:['orders','order-imports','support'],secondary:[]},
  {id:'inventory',label:'库存与补货',defaultRoute:'products',primary:['products','restock'],secondary:[]},
  {id:'connections',label:'店铺连接',defaultRoute:'platforms',primary:['platforms','live'],secondary:[]},
];
const teamSections: NavigationSection[] = [
  {id:'work',label:'工作与交接',defaultRoute:'tasks',primary:['tasks','organization','agent'],secondary:[]},
  {id:'autonomy',label:'自治与成员',defaultRoute:'operating-control',primary:['operating-control','assistant-team'],secondary:[]},
];
const routesOf = (sections: NavigationSection[]) => sections.flatMap(section=>[...section.primary,...section.secondary]);
export const navigation: { id: string; label: string; icon: string; items: string[]; sections?: NavigationSection[] }[] = [
  { id: 'overview', label: '运营台', icon: 'grid', items: ['overview'] },
  { id: 'workspace', label: '商品管线', icon: 'box', items: routesOf(pipelineSections), sections: pipelineSections },
  { id: 'store-ops', label: '店铺运营', icon: 'store', items: routesOf(storeSections), sections: storeSections },
  { id: 'tasks', label: '智能体团队', icon: 'spark', items: routesOf(teamSections), sections: teamSections },
  { id: 'intelligence', label: '情报', icon: 'book', items: ['intelligence', 'exposure'] },
  { id: 'skills', label: '系统', icon: 'gear', items: ['skills', 'tools', 'models', 'connections', 'memory', 'phones'] },
];
export const sectionFor = (route:string) => { const leaf=route.replace('old:',''); return navigation.flatMap(destination=>destination.sections||[]).find(section=>[...section.primary,...section.secondary].includes(leaf)); };
export const storeSectionFor = (route:string) => storeSections.find(section=>[...section.primary,...section.secondary].includes(route.replace('old:','')));
export const destinationFor = (route: string) => navigation.find(destination => destination.items.includes(route.replace('old:', '')));
/** Destination labels do not rename stored conversation or form-draft scopes. */
export const businessModule = (route: string) => {
  const leaf = route.replace('old:', '');
  return leaf==='phones'?'intelligence':['models','memory','assistant-team','operating-control','tools'].includes(leaf) ? 'connections' : ['store-ops','order-imports'].includes(leaf) ? 'orders' : leaf === 'decisions' ? 'insights' : leaf === 'restock' ? 'operations' : ['workspace','workflow','listing'].includes(leaf) ? 'organization' : leaf;
};

/** Restore the saved business page without guessing another case's selection. */
export function conversationDestination(context: { module: string; entity?: { kind: string; id: string } }, pageContext?: unknown): string {
  const caseBound = context.module === 'organization' && context.entity?.kind === 'case';
  const page = pageContext && typeof pageContext === 'object' && 'page' in pageContext ? pageContext.page : null;
  if (typeof page === 'string' && labels[page] && businessModule(page) === context.module
    && (!['workspace', 'listing', 'workflow'].includes(page) || caseBound)) return page;
  return caseBound ? 'workspace' : context.module;
}
