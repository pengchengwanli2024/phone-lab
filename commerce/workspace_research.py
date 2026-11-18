"""Atomic research append and durable request receipts for one current workspace.

Original organization import APIs retain their existing contracts. This writer
only appends local caller-supplied research; it performs no external operation.
"""
import json
import re
from research import canonical, digest, validate

SAVE = 'commerce_workspace_research_save'
CAPABILITIES = 'commerce_workspace_research_capabilities'
VERSION = 'workspace-research-save-v1'
MCP_ANNOTATIONS = {
    SAVE: {'readOnlyHint': False, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': False},
    CAPABILITIES: {'readOnlyHint': True, 'destructiveHint': False, 'idempotentHint': True, 'openWorldHint': False},
}


def definitions(schema, string):
    return [
        (CAPABILITIES, '读取商品研究表单的原子来源/产物版本保存能力；不读取或改动业务资料', schema()),
        (SAVE, '按整个商品来源及当前研究产物版本，原子追加本机research-v1资料并保留幂等回执；缺项保持待核，不发布、采集、调用模型或操作店铺',
         schema({'case_id': {**string, 'minLength': 1, 'maxLength': 160},
                 'record': {'type': 'object', 'description': '原样保留research-v1记录、双语字段及翻译来源；由现有采集校验器严格检查'},
                 'expected_source_sha256': {**string, 'pattern': '^[a-f0-9]{64}$', 'minLength': 64, 'maxLength': 64},
                 'expected_artifact_id': {**string, 'pattern': '^([a-f0-9]{32})?$', 'minLength': 0, 'maxLength': 32,
                                          'description': '打开表单时当前research产物id；确实不存在时为空串'},
                 'idempotency_key': {**string, 'minLength': 1, 'maxLength': 160}},
                ['case_id', 'record', 'expected_source_sha256', 'expected_artifact_id', 'idempotency_key'])),
    ]


class WorkspaceResearch:
    def __init__(self, workspace):
        self.workspace = workspace
        self.core = workspace.core
        self.org = workspace.org
        with self.core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS workspace_research_receipts('
                       'case_id TEXT NOT NULL,idem TEXT NOT NULL,request_sha256 TEXT NOT NULL,'
                       'artifact_id TEXT NOT NULL,receipt TEXT NOT NULL,sha256 TEXT NOT NULL,'
                       'PRIMARY KEY(case_id,idem))')

    @staticmethod
    def capabilities():
        return dict(schema=VERSION, save_tool=SAVE, atomic_source_and_head=True,
                    idempotent_receipt=True, external_execution_allowed=False)

    @staticmethod
    def _scope(case, record):
        scope = case['scope']
        # Exactly the existing organization S1/S5 public-candidate exception.
        public_research = (record.get('platform') == 'research'
                           and scope.get('origin') == 'research_candidate_not_inventory'
                           and bool(scope.get('research_task_id'))
                           and scope.get('inventory_type') == 'candidate'
                           and scope.get('product_id') is None)
        if ((record.get('platform') != scope.get('platform') and not public_research)
                or record.get('market') != scope.get('market')):
            raise ValueError('workspace_research_scope_mismatch')

    def _replay(self, db, case_id, prior, request_sha):
        if prior[0] != request_sha:
            raise ValueError('workspace_research_idempotency_conflict')
        try:
            receipt = json.loads(prior[2])
            intact = digest(canonical(receipt)) == prior[3]
            artifact = db.execute("SELECT payload,sha FROM org_artifacts WHERE id=? AND case_id=? AND kind='research'",
                                  (prior[1], case_id)).fetchone()
            intact = (intact and artifact is not None
                      and digest(canonical(json.loads(artifact[0]))) == artifact[1]
                      and artifact[1] == receipt.get('artifact_sha256')
                      and receipt.get('artifact_id') == prior[1])
        except (ValueError, TypeError, KeyError):
            intact = False
        if not intact:
            raise ValueError('workspace_artifact_changed')
        return receipt

    def save(self, case_id, record, expected_source_sha256, expected_artifact_id, idempotency_key):
        if type(case_id) is not str or not case_id.strip() or len(case_id) > 160:
            raise ValueError('invalid_case_id')
        if type(expected_source_sha256) is not str or not re.fullmatch('[a-f0-9]{64}', expected_source_sha256):
            raise ValueError('invalid_expected_source_sha256')
        if type(expected_artifact_id) is not str or not re.fullmatch('([a-f0-9]{32})?', expected_artifact_id):
            raise ValueError('invalid_expected_artifact_id')
        if type(idempotency_key) is not str or not idempotency_key.strip() or len(idempotency_key) > 160:
            raise ValueError('invalid_idempotency_key')
        try:
            request = canonical(dict(case_id=case_id, record=record,
                                     expected_source_sha256=expected_source_sha256,
                                     expected_artifact_id=expected_artifact_id))
            # Freeze caller-owned nested objects before validating or writing.
            record = json.loads(request)['record']
        except (ValueError, TypeError):
            raise ValueError('invalid_research_record') from None
        request_sha = digest(request)
        # Core.db() calls made by guard(), org.record() and sources() all reuse
        # this BEGIN IMMEDIATE connection. No inner context commits the append.
        with self.core.atomic() as db:
            case = self.org.case(case_id)
            prior = db.execute('SELECT request_sha256,artifact_id,receipt,sha256 FROM workspace_research_receipts WHERE case_id=? AND idem=?',
                               (case_id, idempotency_key)).fetchone()
            if prior:
                return self._replay(db, case_id, prior, request_sha)
            if type(record) is not dict:
                raise ValueError('invalid_research_record')
            self._scope(case, record)
            checked = validate(record)
            self.workspace.guard(case_id, expected_source_sha256)
            head = self.org.artifact(case_id, 'research')
            if (head['id'] if head else '') != expected_artifact_id:
                raise ValueError('workspace_research_conflict')
            payload = dict(record=record, sku=case['scope']['sku'], row_key=case['scope']['row_key'])
            artifact_key = 'workspace-research:' + digest(idempotency_key)
            if db.execute("SELECT 1 FROM org_artifacts WHERE case_id=? AND kind='research' AND idem=?",
                          (case_id, artifact_key)).fetchone():
                raise ValueError('workspace_research_receipt_missing')
            saved = self.org.record(case_id, 'research', payload, artifact_key,
                                    _expected_head=expected_artifact_id or None)
            current_source = self.workspace.sources(case_id)[3]
            receipt = dict(schema=VERSION, case_id=case_id, artifact_id=saved['id'],
                           artifact_sha256=saved['sha256'], source_sha256=current_source,
                           previous_source_sha256=expected_source_sha256,
                           previous_artifact_id=expected_artifact_id,
                           validation_status=checked['status'], issues=checked['issues'],
                           verification='caller_supplied_not_independently_verified',
                           publication_ready=False, external_execution_allowed=False,
                           external_operations_executed=False)
            value = canonical(receipt)
            db.execute('INSERT INTO workspace_research_receipts VALUES (?,?,?,?,?,?)',
                       (case_id, idempotency_key, request_sha, saved['id'], value, digest(value)))
            self.org.case(case_id)  # Match the existing revoked-connection check.
            return json.loads(value)

    def invoke(self, name, args):
        if name == CAPABILITIES:
            return self.capabilities()
        if name == SAVE:
            return self.save(**args)
        raise ValueError('unknown_workspace_research_tool')
