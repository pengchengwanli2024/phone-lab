"""Project extension receipts into the existing shared task API contract."""


class CapabilityTasks:
    def __init__(self,service):self.service=service;self.core=service.core

    def find(self,task_id):
        engineering=getattr(self.service,'engineering',None)
        run=engineering.for_task(task_id) if engineering else None
        if run:return {**run,'_task_owner':'engineering'}
        with self.core.db() as db:
            row=db.execute("SELECT id FROM extension_runs WHERE json_extract(document,'$.task_id')=?",(task_id,)).fetchone()
        if row:return self.service.extensions.run_get(row[0])
        with self.core.db() as db:
            row=db.execute('SELECT id FROM media_plugin_executions WHERE task_id=?',(task_id,)).fetchone()
        return {**self.service.media_plugin_execution.get(row[0]),'_task_owner':'media_plugin'} if row else None

    def result(self,run):
        is_plugin=run.get('_task_owner')=='media_plugin'
        is_engineering=run.get('_task_owner')=='engineering'
        public={k:v for k,v in run.items() if k!='_task_owner'}
        return {'task':self.core.invoke('commerce_task_get',{'task_id':run['task_id']}),
                'execution':{'operation':'engineering' if is_engineering else 'media_plugin' if is_plugin else 'user_extension','attempt':run.get('attempt') if is_engineering else None,'result':public,'error':run.get('error'),
                             'requested_at':run['created_at'],'finished_at':run.get('finished_at')},
                'extension_run_id':None if is_plugin or is_engineering else run['id'],'engineering_run_id':run['id'] if is_engineering else None,
                'media_plugin_execution_id':run['id'] if is_plugin else None,'external_operations_executed':False if is_engineering else None}

    def invoke(self,name,run,args):
        if run.get('_task_owner')=='engineering':
            runtime=self.service.engineering
            if name=='commerce_task_cancel':
                runtime.cancel(run['id']);return self.core.invoke('commerce_task_get',{'task_id':run['task_id']})
            if name=='commerce_task_retry':return self.result({**runtime.resume(run['id']),'_task_owner':'engineering'})
            if name=='commerce_task_result':return self.result(run)
            raise ValueError('engineering_task_use_execution_controls')
        if run.get('_task_owner')=='media_plugin':
            runtime=self.service.media_plugin_execution
            if name=='commerce_task_cancel':
                runtime.cancel(run['id']);return self.core.invoke('commerce_task_get',{'task_id':run['task_id']})
            if name=='commerce_task_retry':
                result=runtime.retry_download(run['id']);return self.result({**result,'_task_owner':'media_plugin'})
            if name=='commerce_task_result':return self.result(run)
            raise ValueError('media_plugin_task_use_execution_controls')
        runtime=self.service.extensions
        if name=='commerce_task_cancel':
            runtime.invoke('commerce_extension_run_cancel',{'run_id':run['id']});return self.core.invoke('commerce_task_get',{'task_id':run['task_id']})
        if name=='commerce_task_retry':return self.result(runtime.resume(run['id']))
        if name=='commerce_task_result':return self.result(run)
        raise ValueError('extension_task_use_capability_runtime')
