"""Explicit synthetic budget and control configuration for browser acceptance."""
import json

from operating_budget import digest


def seed(app):
    task = app.core.invoke('commerce_task_create', {'kind': 'draft', 'idempotency_key': 'SYN-CONTROL-ANCHOR',
        'input': {'demo': True, 'title': '合成预算观察任务', 'origin': 'operating_control',
                  'intake_kind': 'operations', 'budget_actions': [], 'external_execution_allowed': False}})
    candidate = {'mode': 'synthetic', 'cap_minor': 250000, 'task_ids': [task['id']]}
    if app.operating_budget.policy_get('synthetic')['policy']['revision'] == 0:
        app.operating_budget.policy_save('synthetic', '2500.00', [task['id']], 0, 'SYN-CONTROL-POLICY',
            {'kind': 'local_operator', 'name': 'synthetic fixture', 'confirmed': True, 'expected_revision': 0, 'policy_sha256': digest(candidate)})
    (app.state / 'operating-control.json').write_text(json.dumps({'revision': 1, 'platform': 'ozon', 'market': 'RU',
        'fulfillment': 'OGL', 'inventory_location': 'company_local', 'sku_status': 'pending_user', 'logistics_status': 'deferred'}))
