"""Synthetic operating-loop browser fixture: one saved store plan and a scripted model.

No network, real model or marketplace. The scripted model reads the stage brief
through the real runtime and proposes the original organization handoff.
"""
from agent_runtime import model


def install(app, case_id):
    target = {'case_id': case_id, 'platform': 'ozon', 'store_ref': 'ozon-live', 'market': 'RU'}
    view = app.listings.get(**target)
    if not view['revision']:
        app.invoke('commerce_listing_save', {**target, 'payload': view['payload'], 'expected_revision': 0,
                                           'expected_source_sha256': view['source_sha256']}, 'local')
    fallback = model.invoke

    def scripted(payload, cancelled, **kwargs):
        brief = next((t for t in payload.get('tools', []) if t['tool'] == 'commerce_organization_brief'), None)
        if brief is None:
            return fallback(payload, cancelled, **kwargs)
        if cancelled():
            raise model.Cancelled()
        if not payload['observations']:
            decision = {'phase': 'inspect', 'calls': [brief]}
        else:
            decision = {'phase': 'answer', 'answer': '合成验收：该阶段仍有缺项，建议交给负责岗位补齐。', 'questions': [],
                        'evidence_refs': ['R1'], 'proposals': [{'operation': 'organization_handoff',
                        'reason': '合成验收：补齐当前阶段的岗位产物', 'evidence_ref': 'R1'}]}
        return {'decision': decision, 'provider': 'synthetic-no-network', 'model': 'synthetic'}

    model.invoke = scripted
    return target
