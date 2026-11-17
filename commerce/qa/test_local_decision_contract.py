import unittest
from unittest.mock import patch
import jsonschema
from model_providers import inference
from model_providers.decision_contract import decode
from public_web import tool_menu

class LocalDecisionContract(unittest.TestCase):
    def spec(self,payload):
        answer={'decision':{'phase':'answer','answer':'仅供验收','questions':[],'evidence_refs':[],'proposals':[]}}
        from model_providers.grounded_answers import answer_text
        answer['decision']['answer']=answer_text(payload)or answer['decision']['answer']
        with patch.object(inference,'invoke_json',return_value={'decision':answer})as invoked:
            inference.invoke(payload,lambda:False,{'engine':'llama_cpp','json_mode':True})
        return invoked.call_args.kwargs['output_schema'],invoked.call_args.args[0]

    def test_search_arguments_are_typed_not_an_unvalidated_json_string(self):
        spec,_=self.spec({'question':'实时搜索东南亚的公开新闻','evidence_required':True,'tools':tool_menu(),'observations':[]})
        call={'decision':{'phase':'inspect','calls':[{'tool':'commerce_web_search','arguments':{'query':'东南亚物流','regions':['southeast_asia'],'period':'24h'}}]}}
        jsonschema.validate(call,spec)
        for args in [{'query':'新闻','regions':'东南亚'},{'query':'新闻','regions':['东南亚']},{'query':'新闻','refresh':'true'},{'query':'新闻','period':'future'}]:
            call['decision']['calls'][0]['arguments']=args
            with self.subTest(args=args),self.assertRaises(jsonschema.ValidationError):jsonschema.validate(call,spec)

    def test_explicit_three_regions_and_window_cannot_be_widened_or_dropped(self):
        payload={'question':'检索过去24小时东南亚、俄罗斯、中东公开新闻并读取原文','tools':tool_menu()}
        spec,_=self.spec(payload)
        args={'query':'公开新闻','regions':['southeast_asia','russia','middle_east'],'period':'24h'}
        value={'decision':{'phase':'inspect','calls':[{'tool':'commerce_web_search','arguments':args}]}}
        jsonschema.validate(value,spec)
        for field,replacement in [('period','any'),('regions',['russia'])]:
            changed=__import__('copy').deepcopy(value);changed['decision']['calls'][0]['arguments'][field]=replacement
            with self.assertRaises(jsonschema.ValidationError):jsonschema.validate(changed,spec)

    def test_provided_cost_input_is_read_before_answer_or_unrelated_tools(self):
        parameters={'context':{'module':'operations','calculator':'unit_economics','input':{'price':100,'currency':'CNY'}}}
        payload={'question':'请核对成本测算缺项','parameters':parameters,'evidence_required':True,'observations':[],
                 'tools':[{'tool':'commerce_unit_economics','arguments':{'input':parameters['context']['input']}},*tool_menu()]}
        spec,_=self.spec(payload)
        good={'decision':{'phase':'inspect','calls':[{'tool':'commerce_unit_economics','arguments':{'input':parameters['context']['input']}}]}}
        jsonschema.validate(good,spec)
        good['decision']['calls'][0]['arguments']['input']={'price':999,'currency':'CNY'}
        with self.assertRaises(jsonschema.ValidationError):jsonschema.validate(good,spec)

    def test_readonly_workspace_does_not_offer_unrelated_report_or_handoff(self):
        spec,payload=self.spec({'question':'只读核对，不创建交接任务','evidence_required':True,'tools':[],
            'parameters':{'context':{'entity':{'kind':'case','id':'test'}}},
            'observations':[{'id':'R1','tool':'commerce_workspace_get','data':{}}],'ui_catalog':{'choices':[]}})
        answer=spec['properties']['decision']['anyOf'][0]
        self.assertEqual(answer['properties']['proposals']['maxItems'],0)
        self.assertNotIn('ui',answer['properties']);self.assertNotIn('ui_catalog',payload)

    def test_direct_and_legacy_decisions_decode_without_scope_changes(self):
        call={'phase':'inspect','calls':[{'tool':'commerce_unit_economics','arguments':{'input':{'price':100}}}]}
        self.assertEqual(decode({'decision':call}),call)
        with self.assertRaises(ValueError):decode({'decision':{'phase':'inspect','calls':[{'tool':'x','arguments':[]}]}})
