import type { Surface, Task } from './types';

/** A task label is not a binding: re-read the shared Surface before resuming. */
export async function readTaskCostSurface(
  request: (tool: string, args: object) => Promise<Surface>,
  task: Pick<Task, 'id' | 'input'>,
): Promise<Surface | null> {
  const id = task.input.surface_id;
  if (typeof id !== 'string' || !/^cost_[0-9a-f]{32}$/.test(id)) return null;
  const surface = await request('commerce_a2ui_get', { surface_id: id });
  if (surface.surface_id !== id || surface.task_id !== task.id) throw Error('cost_task_changed');
  return surface;
}
