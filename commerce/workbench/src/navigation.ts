/** Business destinations are flat; old routes remain addressable within them. */
export const labels: Record<string, string> = {
  overview: '运营台', workspace: '商品工作区', orders: '订单', products: '库存', operations: '通用成本',
  agent: '执行记录', exposure: '经营关联', platforms: '平台数据', pilots: '商品候选', live: 'Ozon 经营',
  alerts: '经营提醒', research: '研究资料', creative: '创意工作室', skills: '技能', intelligence: '全球情报',
  insights: '选品与评论', support: '客服', organization: '岗位交接', tasks: '任务记录', connections: '接入与知识', models: '模型管理', restock: '补货计划',
};
export const navigation: { id: string; label: string; icon: string; items: string[] }[] = [
  { id: 'overview', label: '运营台', icon: 'grid', items: ['overview'] },
  { id: 'workspace', label: '商品', icon: 'box', items: ['workspace', 'pilots', 'research', 'insights', 'operations'] },
  { id: 'orders', label: '店铺管理', icon: 'store', items: ['orders', 'products', 'restock', 'support', 'alerts', 'live', 'platforms'] },
  { id: 'creative', label: '内容', icon: 'image', items: ['creative'] },
  { id: 'intelligence', label: '情报', icon: 'book', items: ['intelligence', 'exposure'] },
  { id: 'tasks', label: '任务', icon: 'clock', items: ['tasks', 'organization', 'agent'] },
  { id: 'skills', label: '能力库', icon: 'bolt', items: ['skills', 'models', 'connections'] },
];
export const destinationFor = (route: string) => navigation.find(destination => destination.items.includes(route.replace('old:', '')));
/** Destination labels do not rename stored conversation or form-draft scopes. */
export const businessModule = (route: string) => {
  const leaf = route.replace('old:', '');
  return leaf === 'models' ? 'connections' : leaf === 'restock' ? 'operations' : leaf === 'workspace' ? 'organization' : leaf;
};
