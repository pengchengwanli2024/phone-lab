"""A visual projection of the existing product plan, not a second scheduler."""
from copy import deepcopy
import json
import math
import re


def validate_plan(payload, task_ids):
    if type(payload) is not dict or set(payload) - {'goal', 'steps', 'graph'} or not {'goal', 'steps'} <= set(payload):
        raise ValueError('workspace_invalid_plan')
    if type(payload['goal']) is not str or len(payload['goal']) > 2000 or type(payload['steps']) is not list or len(payload['steps']) > 12:
        raise ValueError('workspace_invalid_plan')
    ids = []
    for step in payload['steps']:
        if type(step) is not dict or set(step) - {'title', 'task_id', 'id'} or type(step.get('title')) is not str or not 1 <= len(step['title'].strip()) <= 160:
            raise ValueError('workspace_invalid_plan')
        if step.get('task_id') is not None and (type(step['task_id']) is not str or step['task_id'] not in task_ids):
            raise ValueError('workspace_task_outside_scope')
        if 'id' in step and (type(step['id']) is not str or not re.fullmatch('[a-zA-Z0-9_-]{1,80}', step['id']) or step['id'] in ('__proto__', 'constructor', 'prototype')):
            raise ValueError('workflow_invalid_node')
        ids.append(step.get('id'))
    defined = [i for i in ids if i is not None]
    if len(set(defined)) != len(defined):raise ValueError('workflow_invalid_node')
    if 'graph' not in payload:return
    if None in ids or len(set(ids)) != len(ids):raise ValueError('workflow_invalid_node')
    graph = payload['graph']
    if type(graph) is not dict or set(graph) != {'edges', 'positions'} or type(graph['edges']) is not list or len(graph['edges']) > 66 or type(graph['positions']) is not dict:
        raise ValueError('workflow_invalid_graph')
    indegree = {i: 0 for i in ids};links = {i: [] for i in ids};seen = set()
    for edge in graph['edges']:
        if type(edge) is not dict or set(edge) != {'from', 'to'} or any(type(v) is not str or v not in indegree for v in edge.values()):
            raise ValueError('workflow_invalid_edge')
        pair = edge['from'], edge['to']
        if pair in seen:raise ValueError('workflow_duplicate_edge')
        seen.add(pair);indegree[pair[1]] += 1;links[pair[0]].append(pair[1])
    queue = [i for i in ids if indegree[i] == 0];order = []
    while queue:
        current = queue.pop(0);order.append(current)
        for target in links[current]:
            indegree[target] -= 1
            if indegree[target] == 0:queue.append(target)
    if len(order) != len(ids):raise ValueError('workflow_cycle')
    for ident, point in graph['positions'].items():
        if ident not in indegree or type(point) is not dict or set(point) != {'x', 'y'} or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 4000 for v in point.values()):
            raise ValueError('workflow_invalid_position')


def normalized(payload):
    plan = deepcopy(payload or {'goal': '', 'steps': []})
    used = {step['id'] for step in plan['steps'] if 'id' in step}
    for step in plan['steps']:
        if 'id' not in step:
            i = 1
            while 'step_' + str(i) in used:i += 1
            step['id'] = 'step_' + str(i);used.add(step['id'])
    ids = [step['id'] for step in plan['steps']]
    plan.setdefault('graph', {'edges': [{'from': a, 'to': b} for a, b in zip(ids, ids[1:])], 'positions': {}})
    for i, ident in enumerate(ids):plan['graph']['positions'].setdefault(ident, {'x': 40 + (i % 3) * 230, 'y': 40 + (i // 3) * 130})
    return plan


def preserve_graph(payload, previous):
    """Legacy text editors preserve graph data for surviving identified steps."""
    if type(payload) is not dict or 'graph' in payload or not previous or 'graph' not in previous:return payload
    if type(payload.get('steps')) is not list or any(type(s) is not dict for s in payload['steps']):return payload
    merged = deepcopy(payload);ids = {step.get('id') for step in merged.get('steps', []) if isinstance(step, dict)}
    graph = previous['graph']
    # Missing IDs get fresh values; never reuse an old node's edges by index.
    used = {step['id'] for step in previous['steps']}
    for step in merged.get('steps', []):
        if 'id' not in step:
            i = 1
            while 'step_' + str(i) in used:i += 1
            step['id'] = 'step_' + str(i);used.add(step['id']);ids.add(step['id'])
    merged['graph'] = {'edges': [edge for edge in graph['edges'] if edge['from'] in ids and edge['to'] in ids],
                       'positions': {k: v for k, v in graph['positions'].items() if k in ids}}
    return merged


class WorkflowPlans:
    def __init__(self, service):self.service = service

    def get(self, case_id):
        workspace = self.service.product_workspace.get(case_id)
        checkpoint = workspace['forms']['plan']
        from research import digest
        versions=[]
        with self.service.core.db()as db:
            for raw,sha,created in db.execute("SELECT payload,sha,created FROM org_artifacts WHERE case_id=?AND kind='workflow_plan_version'ORDER BY created DESC,id DESC LIMIT 20",(case_id,)):
                if digest(raw)!=sha:raise ValueError('workspace_plan_version_integrity')
                record=json.loads(raw);versions.append({**record,'sha256':sha,'created_at':created,'stale':record['source_sha256']!=workspace['source_sha256']})
        return {'case_id': case_id, 'name': workspace['name'], 'revision': checkpoint['revision'],
                'source_sha256': workspace['source_sha256'], 'stale': checkpoint['stale'],
                'payload': normalized(checkpoint['payload']), 'tasks': workspace['tasks'],'versions':versions,
                'external_execution_allowed': False, 'execution_mode': 'existing_tasks_only'}

    def save(self, case_id, payload, expected_revision, expected_source_sha256):
        self.service.product_workspace.save(case_id, 'plan', payload, expected_revision, expected_source_sha256)
        return self.get(case_id)

    def invoke(self, name, args):return {'get': self.get, 'save': self.save}[name.removeprefix('commerce_workflow_plan_')](**args)


def definitions(schema):
    s = {'type': 'string', 'minLength': 1, 'maxLength': 160}
    return [
        ('commerce_workflow_plan_get', '将原商品工作计划投影为步骤依赖图；旧计划不自动改写，不创建任务。', schema({'case_id': s}, ['case_id'])),
        ('commerce_workflow_plan_save', '按原商品来源和计划修订保存步骤、DAG依赖和画布位置；关联任务须属于同一商品，不自动执行。', schema({
            'case_id': s, 'payload': {'type': 'object'}, 'expected_source_sha256': s,
            'expected_revision': {'type': 'integer', 'minimum': 0}}, ['case_id', 'payload', 'expected_source_sha256', 'expected_revision'])),
    ]
