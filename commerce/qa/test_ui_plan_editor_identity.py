"""The real product plan editor must round-trip existing task/graph identities."""
from copy import deepcopy
from pathlib import Path
import json,subprocess,sys,unittest
sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import test_paos_round2 as fixtures

class ProductPlanEditorIdentity(unittest.TestCase):
 def setUp(self):
  self.fixture=fixtures.WorkflowPlans();self.fixture.setUp();self.app=self.fixture.app
  self.tasks=[self.app.core.invoke('commerce_task_create',{'kind':'analysis','input':{'organization_case':self.fixture.case},'idempotency_key':'plan-ui-'+str(i)}) for i in range(2)]
  self.plan={'goal':'Original goal','steps':[{'id':'step_a','title':'Same title','task_id':self.tasks[0]['id']},{'id':'step_b','title':'Same title','task_id':self.tasks[1]['id']}],'graph':{'edges':[{'from':'step_a','to':'step_b'}],'positions':{'step_a':{'x':40,'y':60},'step_b':{'x':200,'y':60}}}}
  self.saved=self.fixture.save(deepcopy(self.plan),self.fixture.get())
  self.before_tasks=self.app.core.invoke('commerce_task_list',{})
 def tearDown(self):
  self.app.agent_runtime.stop();self.fixture.tearDown()
 def edit(self,action):
  root=Path(__file__).resolve().parents[2]
  code="""import {readFileSync} from 'node:fs';import {planEditorFixture} from './commerce/workbench/tests/helpers/product-plan-editor.mjs';const input=JSON.parse(readFileSync(0,'utf8'));const f=planEditorFixture(input.payload,input.options);f.open();f.input('pw-goal','Edited goal');if(input.action==='rename')f.input('step_b','Renamed second');if(input.action==='remove')await f.action('plan-step-remove','step_a');if(input.action==='reorder')await f.action('plan-step-up','step_b');await f.action('save-plan');console.log(JSON.stringify(f.requests[0]));"""
  args={'payload':self.plan,'action':action,'options':{'caseId':self.fixture.case,'revision':self.saved['revision'],'sourceSha':self.saved['source_sha256']}}
  call=json.loads(subprocess.check_output(['node','--input-type=module','-e',code],input=json.dumps(args).encode(),cwd=root))
  self.app.invoke(call['tool'],call['args'],'test')
  current=self.fixture.get()['payload'];self.assertEqual(current['goal'],'Edited goal')
  self.assertEqual(self.app.core.invoke('commerce_task_list',{}),self.before_tasks)
  return current
 def test_duplicate_titles_and_rename_preserve_two_tasks_and_graph(self):
  current=self.edit('rename');self.assertEqual([s['id']for s in current['steps']],['step_a','step_b'])
  self.assertEqual([s['task_id']for s in current['steps']],[t['id']for t in self.tasks]);self.assertEqual(current['steps'][1]['title'],'Renamed second');self.assertEqual(current['graph'],self.plan['graph'])
 def test_explicit_reorder_preserves_graph_and_each_task(self):
  current=self.edit('reorder');self.assertEqual([s['id']for s in current['steps']],['step_b','step_a']);self.assertEqual(current['graph'],self.plan['graph'])
 def test_removal_prunes_only_removed_step_dependencies(self):
  current=self.edit('remove');self.assertEqual(current['steps'],[self.plan['steps'][1]]);self.assertEqual(current['graph'],{'edges':[],'positions':{'step_b':self.plan['graph']['positions']['step_b']}})
