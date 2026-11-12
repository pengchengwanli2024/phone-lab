import type { BusinessContext, Product } from './types';

/** Use the same saved product identity as its native product view. */
export function productScope(context: BusinessContext, product: Product): BusinessContext {
  if (context.entity?.kind !== 'case' || product.case.id !== context.entity.id) throw Error('workspace_source_changed');
  return { module: 'organization', demo: product.case.scope.synthetic === true,
    ...(product.case.scope.platform ? { platform: product.case.scope.platform } : {}),
    ...(product.case.scope.market ? { market: product.case.scope.market } : {}),
    entity: { kind: 'case', id: product.case.id } };
}
