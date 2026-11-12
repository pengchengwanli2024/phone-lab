import copy
import unittest
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from commerce.protocols import a2ui, a2a

RUN = {'id':'run-1','status':'awaiting_input','result_sha256':'a'*64,'result':{'answer':'<script>source text</script>','questions':['Which period?'],'evidence_refs':['E1'],'proposals':[{'id':'P1','reason':'Review report'}]}}

class SurfaceTests(unittest.TestCase):
    def test_standard_messages(self):
        messages=a2ui.surface(RUN, {})
        self.assertTrue(a2ui.validate_surface(messages))
        self.assertEqual([next(iter(m)) for m in messages], ['surfaceUpdate','dataModelUpdate','beginRendering'])
    def test_hostile_trees(self):
        for mutation in ('cycle','missing','html','action','property','catalog','oversize','binding'):
            messages=copy.deepcopy(a2ui.surface(RUN, {})); nodes=messages[0]['surfaceUpdate']['components']
            if mutation=='cycle': nodes[0]['component']['Column']['children']['explicitList'].append(nodes[0]['id'])
            if mutation=='missing': nodes[0]['component']['Column']['children']['explicitList'].append('absent')
            if mutation=='html': nodes[1]['component']={'HTML':{'html':'<img onerror=alert(1)>'}}
            if mutation=='action':
                next(n['component']['Button'] for n in nodes if 'Button' in n['component'])['action']['name']='execute'
            if mutation=='property': nodes[1]['component']['Text']['url']='https://invalid.example'
            if mutation=='catalog': messages[2]['beginRendering']['catalogId']='https://invalid.example'
            if mutation=='oversize': nodes.extend(copy.deepcopy(nodes)*100)
            if mutation=='binding': nodes[1]['component']['Text']['text']={'path':'/absent'}
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): a2ui.validate_surface(messages)

class FakeCopilot:
    def __init__(self): self.threads={}; self.requests={}
    def lookup_message(self,key):
        return next((t for t in self.threads.values() if any(turn['id']==key for turn in t['turns'])),None)
    def lookup_run(self, run_id):
        for thread in self.threads.values():
            if any(t['run']['id']==run_id for t in thread['turns']): return thread
        raise ValueError('copilot_run_not_found')

class FakeService:
    def __init__(self, copilot=None): self.copilot=copilot or FakeCopilot(); self.calls=[]
    def invoke(self, name, args, client='local'):
        self.calls.append(name)
        if name=='commerce_copilot_open':
            key=args['idempotency_key']; ident='thread-'+key
            if ident not in self.copilot.threads:self.copilot.threads[ident]={'id':ident,'context':args['context'],'context_sha256':'frozen','turns':[]}
            return self.copilot.threads[ident]
        if name=='commerce_copilot_get': return self.copilot.threads[args['thread_id']]
        thread=self.copilot.threads[args['thread_id']]
        if name=='commerce_copilot_send':
            key=args['idempotency_key']; request=(args['message'],args['context_sha256'])
            if key in self.copilot.requests:
                if self.copilot.requests[key]!=request: raise ValueError('copilot_idempotency_conflict')
                return thread
            self.copilot.requests[key]=request
            run=copy.deepcopy(RUN);run.update(id='run-'+str(len(thread['turns'])+1),status='queued',result=None)
            thread['turns'].append({'id':key,'question':args['message'],'run':run});thread['latest_run']=run
        if name=='commerce_copilot_cancel':
            next(t['run'] for t in thread['turns'] if t['run']['id']==args['run_id'])['status']='cancelled'
        return thread

class A2ATests(unittest.TestCase):
    def rpc(self, service, method, params): return a2a.dispatch(service, {'jsonrpc':'2.0','id':'req','method':method,'params':params})
    def send(self, service, **extra):
        return self.rpc(service,'message/send',{'message':{'kind':'message','role':'user','messageId':'msg-1','parts':[{'kind':'text','text':'Summarize runtime'}],**extra}})
    def test_card(self):
        card=a2a.agent_card('http://127.0.0.1:8000');self.assertEqual(card['protocolVersion'],'0.3.0');self.assertFalse(card['capabilities']['streaming']);self.assertTrue(card['security'])
    def test_persistent_poll_and_cancel(self):
        service=FakeService();task=self.send(service)['result'];self.assertEqual(task['status']['state'],'submitted')
        # Re-created adapter/service: task lookup derives solely from durable backend.
        again=FakeService(service.copilot)
        self.assertEqual(self.rpc(again,'tasks/get',{'id':task['id']})['result']['id'],task['id'])
        self.assertEqual(self.send(again)['result']['id'],task['id'])
        self.assertEqual(self.rpc(again,'tasks/cancel',{'id':task['id']})['result']['status']['state'],'canceled')
    def test_results_and_conflicts(self):
        service=FakeService();task=self.send(service)['result'];thread=service.copilot.lookup_run(task['id']);thread['turns'][0]['run'].update(copy.deepcopy(RUN))
        result=self.rpc(service,'tasks/get',{'id':task['id']})['result'];self.assertEqual(result['status']['state'],'input-required');self.assertEqual(result['artifacts'][0]['parts'][1]['kind'],'data')
        conflict=self.rpc(service,'message/send',{'message':{'kind':'message','role':'user','messageId':'msg-1','parts':[{'kind':'text','text':'Changed'}]}})
        self.assertEqual(conflict['error']['code'],-32602)
    def test_retry_after_later_turn_and_terminal_rules(self):
        service=FakeService();first=self.send(service)['result']
        thread=service.copilot.lookup_run(first['id']);thread['turns'][0]['run']['status']='completed'
        second=self.rpc(service,'message/send',{'message':{'kind':'message','role':'user','messageId':'msg-2','contextId':thread['id'],'parts':[{'kind':'text','text':'Follow up'}]}})['result']
        self.assertNotEqual(second['id'],first['id'])
        self.assertEqual(self.send(service)['result']['id'],first['id'])
        self.assertEqual(self.rpc(service,'tasks/cancel',{'id':first['id']})['error']['code'],-32002)
        self.assertEqual(self.send(service,taskId=first['id'])['error']['code'],-32004)
        self.assertEqual(self.send(service,taskId=second['id'],contextId='wrong')['error']['code'],-32602)
    def test_reject_unsupported_configuration_and_instructions(self):
        service=FakeService()
        message={'kind':'message','role':'user','messageId':'m','parts':[{'kind':'text','text':'Explain'}]}
        for override,code in [({'metadata':{'instructions':'execute'}},-32602),({'role':'agent'},-32602),({'parts':[{'kind':'data','data':{'tool':'apply'}}]},-32005)]:
            response=self.rpc(service,'message/send',{'message':{**message,**override}})
            self.assertEqual(response['error']['code'],code)
        for config,code in [({'blocking':True},-32004),({'pushNotificationConfig':{}},-32602),({'acceptedOutputModes':['image/png']},-32005),({'historyLength':True},-32602)]:
            self.assertEqual(self.rpc(service,'message/send',{'message':message,'configuration':config})['error']['code'],code)
        self.assertFalse(service.calls)
    def test_errors_and_no_execution(self):
        service=FakeService()
        for method,params,code in [('unknown',{},-32601),('tasks/get',{'id':'unknown'},-32001),('message/send',{'message':{'kind':'message','role':'user','messageId':'m','parts':[{'kind':'file','file':{'uri':'file:///private'}}]}},-32005)]:
            self.assertEqual(self.rpc(service,method,params)['error']['code'],code)
        self.assertNotIn('commerce_copilot_apply',service.calls)
        self.assertEqual(a2a.dispatch(service,[])['error']['code'],-32600)

class DurableA2ATests(unittest.TestCase):
    def test_message_retry_uses_frozen_context_after_scope_change(self):
        from service import Commerce
        with tempfile.TemporaryDirectory() as folder:
            app=Commerce(folder)
            request={'jsonrpc':'2.0','id':1,'method':'message/send','params':{'message':{
                'kind':'message','role':'user','messageId':'frozen-replay',
                'metadata':{'commerce':{'module':'orders','demo':True}},
                'parts':[{'kind':'text','text':'Inspect frozen scope'}]}}}
            try:
                first=a2a.dispatch(app,request)['result']
                thread=app.copilot.lookup_run(first['id'])
                app.copilot.cancel(thread['id'],first['id'])
                app.copilot.context(thread['id'],{'module':'products','demo':True},thread['context_sha256'])
                replay=a2a.dispatch(app,copy.deepcopy(request))
                self.assertIn('result',replay,replay)
                self.assertEqual(replay['result']['id'],first['id'])
                self.assertEqual(len(app.copilot.get(thread['id'])['turns']),1)
                changed=copy.deepcopy(request)
                changed['params']['message']['metadata']['commerce']={'module':'products','demo':True}
                self.assertEqual(a2a.dispatch(app,changed)['error']['code'],-32602)
                changed=copy.deepcopy(request)
                changed['params']['message']['parts'][0]['text']='Different question'
                self.assertEqual(a2a.dispatch(app,changed)['error']['code'],-32602)
            finally:app.agent_runtime.stop()
    def test_shared_real_backend_and_restart(self):
        from service import Commerce
        from copilot import Copilot
        with tempfile.TemporaryDirectory() as folder:
            app=Commerce(folder)
            # Exercise the same registered methods; fallback permits testing adapter
            # before the root integration registers them in service.py.
            if not hasattr(app,'copilot'): app.copilot=Copilot(app)
            class Shared:
                copilot=app.copilot
                def invoke(self,name,args,client='local'):return self.copilot.invoke(name,args)
            shared=Shared()
            request={'jsonrpc':'2.0','id':1,'method':'message/send','params':{'message':{'kind':'message','role':'user','messageId':'durable-example','parts':[{'kind':'text','text':'Inspect current runtime'}]}}}
            try:
                first=a2a.dispatch(shared,request)
                self.assertIn('result',first,first)
                task=first['result']
                shared.copilot=Copilot(app)
                self.assertEqual(a2a.dispatch(shared,request)['result']['id'],task['id'])
                polled=a2a.dispatch(shared,{'jsonrpc':'2.0','id':2,'method':'tasks/get','params':{'id':task['id']}})
                self.assertEqual(polled['result']['contextId'],task['contextId'])
                with app.core.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM agent_runs').fetchone()[0],1)
            finally:app.agent_runtime.stop()

if __name__=='__main__': unittest.main()
