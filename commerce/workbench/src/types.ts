export type Input = Partial<Record<'currency' | 'price' | 'purchase_cost' | 'domestic_shipping' | 'packaging' | 'fulfillment_cost' | 'electronic_fee' | 'commission_rate' | 'payment_rate' | 'return_rate' | 'ad_rate', string | number | null>>;
export interface Calculation {
  status: 'HOLD' | 'CALCULATED'; currency?: string; missing: string[];
  price?: number; contribution: number | null; total_cost: number | null;
  contribution_rate: number | null; cost_breakdown?: Record<string, number>;
}
export interface Surface {
  surface_id: string; task_id: string | null; revision: number; input: Input; result: Calculation | null;
  binding?: { case_id: string; source_sha256: string; cost_revision: number; stale: boolean };
  messages: import('@copilotkit/shared').A2UIOperation[];
  updates: import('@copilotkit/shared').A2UIOperation[];
}
export interface Task {
  id: string; status: string; kind: string;
  input: { title?: string; organization_case?: string; [key: string]: unknown };
}
export interface CaseItem { id: string; name: string; platform?: string; market?: string; candidate: boolean; synthetic: boolean }
export interface Checkpoint<T> { revision: number; payload: T | null; stale: boolean }
export interface Product {
  name: string; source_sha256: string;
  case: { id: string; currency: string | null; scope: { platform?: string; market?: string; sku?: string; synthetic?: boolean } };
  stages: { id: string; name: string; status: string; role: string; gaps: { reason: string; owner: string; verify: string }[] }[];
  forms: { plan: Checkpoint<{ goal: string; steps: { title: string; task_id?: string }[] }>; cost: Checkpoint<{ input: Input }> };
  calculation: Calculation; tasks: Task[];
}
export interface BusinessContext { module: string; demo?: boolean; platform?: string; market?: string; store_id?: string; store_scope?: string; entity?: { kind: string; id: string }; calculator?: string; input?: Input }
export interface PageContext { page: string; section?: string; demo?: boolean; source?: 'live'|'local'|'unavailable'|'stale'; entity?: {kind:string;id:string;name?:string}; filters?: Record<string,string>; source_refs?: Record<string,string>; input?: Record<string,string|number|null>; errors?: string[]; intent?: 'current_page'|'original_thread' }
export interface SharedCopilotController {
  view: () => string; open: (context?: BusinessContext, options?: { focus?: boolean }) => void;
  close: () => void; afterPaint: () => void; contextChanged: () => void; dispose: () => void;
  openThread: (id: string) => Promise<void>;
}
interface SharedCopilotOptions {
  api: (tool: string, args?: object) => Promise<unknown>; getContext: () => BusinessContext;
  getPageContext?: () => PageContext;
  isActive: () => boolean; repaint: () => void; inline: boolean; compact: boolean;
  modal: (title: string, body: string, actions?: string) => void; closeModal: (focusId?: string) => void;
  toast: (text: string) => void; onWorkspace: () => void;
  onModels?: () => void; onResearch?: (taskId: string) => void; onOpenCandidate?: (caseId: string, researchTaskId?: string) => void;
  errorText: (failure: Error | { code?: string; message?: string }) => string;
}
export interface Run {
  id: string; status: string; result_sha256?: string; error?: string;
  parameters?: { context?: BusinessContext; page_context?: PageContext };
  result?: { answer?: string; questions?: string[]; evidence_refs?: string[]; proposals?: { id: string; reason: string }[] };
}
export interface Thread {
  id: string; title: string; context: BusinessContext; context_sha256: string;
  turns: { id: string; question: string; run: Run }[]; latest_run: Run | null;
  has_more?: boolean; next_cursor?: string;
}
export interface OpsAlert { id: string; title: string; status: string; severity: string; detail: string; kind: string; sku?: string; store_id?: string; source_ref?: string }
export interface LiveStatus {
  configured: boolean; orders_scope_confirmed: boolean;
  orders?: { available: boolean; fresh: boolean; count?: number };
  stock?: { available: boolean; fresh: boolean; count?: number };
}
export type Theme = 'light' | 'dark' | 'system';
interface RunEventObserver {
  observe: (options: {
    api: (tool: string, args: object) => Promise<unknown>; thread: Thread; runId: string;
    pollMs?: number; eventThreadId?: string; eventRunId?: string;
    onEvent?: (event: import('@ag-ui/client').BaseEvent) => void;
    onComplete?: (thread: Thread) => void; onError?: (error: Error, thread?: Thread) => void;
  }) => () => void;
}
declare global {
  var CommerceRunEvents: RunEventObserver;
  const __LEGACY_HTML__: string;
  interface Window {
    CommercePageContext: { clean:(value:unknown)=>PageContext|null;label:(value:PageContext)=>string;create:(options:{getBase:()=>PageContext;root?:()=>HTMLElement|null;onChange?:(value:PageContext|null)=>void})=>{snapshot:()=>PageContext|null;changed:()=>void;reset:()=>void;dispose:()=>void} };
    CommerceResearchContext: { task: (value?: string | null) => string; mergeJob: <T extends { task_id: string; revision?: string | number }>(jobs: T[], readback: T) => T[]; mergeJobs: <T extends { task_id: string; revision?: string | number }>(jobs: T[], readback: T[]) => T[] };
    CommerceCopilotDraftStorage: () => { request: (op: string, key: string, value?: string, expected?: string) => Promise<string>; dispose: () => void };
    CommerceCopilot: (options: SharedCopilotOptions) => SharedCopilotController;
    CommerceUI: { icon: (name: string) => string; applyTheme: (theme: string) => void; chatLayout: (areaWidth: number, preferred?: number | string | null) => { min: number; max: number; width: number }; status: (status: string) => { label: string; tone: string }; fieldDiff: (props: { rows: { key: string; label: string; before: unknown; after: unknown }[]; beforeLabel?: string; afterLabel?: string }) => string };
  }
}
