import { useMemo, type ReactNode } from 'react';
import { GenerativeUISurfaceManager, createGenerativeUIDispatcher } from '@copilotkit/core/generative-ui';
import { GenerativeUIRuntimeContext, type GenerativeUIRuntime } from '@copilotkit/react-core/v2/generative-ui/native';
import { commerceUI } from './calculation';

/** Public OSS surface engine. Chat continues to use the authorized Python runner.
 * No Enterprise selfManagedAgents, remote runtime, telemetry, or model key.
 */
export function SurfaceProvider({ children }: { children: ReactNode }) {
  const runtime = useMemo<GenerativeUIRuntime>(() => ({
    manager: new GenerativeUISurfaceManager(commerceUI),
    dispatcher: createGenerativeUIDispatcher({ getDeclared: () => new Map() }),
    ui: commerceUI, transport: 'tool', config: { ui: commerceUI },
    forwardEvent: async () => { throw Error('surface_action_requires_explicit_host_handler'); },
    reportError: () => {},
  }), []);
  return <GenerativeUIRuntimeContext.Provider value={runtime}>{children}</GenerativeUIRuntimeContext.Provider>;
}
