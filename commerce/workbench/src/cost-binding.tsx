import { Children, createContext, isValidElement, type ReactNode } from 'react';
import { costFieldByNode, costNodes } from './cost-contract';

export const CostNodeIdentity = createContext<string>(costNodes.root);

/** SurfaceView 1.87 passes slotted NodeView elements carrying componentId.
 * Its node context is private. Keep this adapter explicit and fail closed if
 * the renderer changes; the real renderer contract test exercises this seam.
 * Labels, array offsets and child counts never carry business identity.
 */
export function costSlotNodes(children: ReactNode) {
  return Children.toArray(children).map(child => {
    const id = isValidElement<{ componentId?: unknown }>(child) && typeof child.props.componentId === 'string' ? child.props.componentId : undefined;
    return { id, field: id ? costFieldByNode[id] : undefined, child: id ? <CostNodeIdentity.Provider key={id} value={id}>{child}</CostNodeIdentity.Provider> : null };
  });
}
