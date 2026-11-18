"""Read-only: who, if anyone, will pick up each queued shared task.

A queued task without an execution request, research job, extension/engineering
run or media execution has no executor; it waits for an explicit execute or
cancel. Reporting it as "running" would hide that. Nothing here dispatches.
"""
READ_ONLY = {'commerce_task_dispatch_get'}


def definitions(schema, string):
    return [('commerce_task_dispatch_get', '读取排队中的共享任务由谁执行；无执行者的任务需明确执行或取消，本接口不派发', schema())]


class TaskDispatch:
    def __init__(self, service):
        self.service, self.core = service, service.core

    def invoke(self, name, args):
        if name != 'commerce_task_dispatch_get':
            raise ValueError('unknown_tool')
        return self.get(**args)

    def get(self):
        with self.core.db() as db:
            names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            queued = [r[0] for r in db.execute("SELECT id FROM tasks WHERE status='queued' ORDER BY rowid DESC LIMIT 500")]
            def owned(sql, table):
                return {r[0] for r in db.execute(sql)} if table in names else set()
            local = owned('SELECT task_id FROM task_runs', 'task_runs')
            research = owned('SELECT task_id FROM market_research_jobs', 'market_research_jobs')
            extension = owned("SELECT json_extract(document,'$.task_id') FROM extension_runs", 'extension_runs')
            media = owned('SELECT task_id FROM media_plugin_executions', 'media_plugin_executions')
        engineering = getattr(self.service, 'engineering', None)
        items = {}
        for ident in queued:
            if ident in local: state = 'local_executor'
            elif ident in research: state = 'market_research'
            elif ident in extension: state = 'extension_runtime'
            elif ident in media: state = 'media_plugin'
            elif engineering and engineering.for_task(ident): state = 'engineering'
            else: state = 'unassigned'
            items[ident] = state
        return {'schema': 'commerce-task-dispatch-v1', 'items': items, 'unassigned': sum(v == 'unassigned' for v in items.values()),
                'truncated': len(queued) >= 500, 'dispatches': False}
