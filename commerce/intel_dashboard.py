"""Shared dashboard view choices, with validation and optimistic concurrency."""
import copy
import json
from intel_map import EVENT_LAYERS, PANEL_IDS, REGIONS, TIMES, REFERENCES, catalog, validate_layers


def defaults():
    return dict(layers=[*EVENT_LAYERS, 'waterways', 'flights'],
                panels=[dict(id=k, visible=True, collapsed=False, wide=False) for k in PANEL_IDS],
                language='zh', time='all', region='global', link_map=False)


def validate(value):
    expected = defaults()
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError('invalid_intel_dashboard_preferences')
    try:
        if not isinstance(value['layers'], list):
            raise ValueError()
        validate_layers(value['layers'])
        if value['language'] not in ('zh', 'original') or value['time'] not in TIMES or value['region'] not in REGIONS:
            raise ValueError()
        if type(value['link_map']) is not bool or not isinstance(value['panels'], list) or len(value['panels']) != len(PANEL_IDS):
            raise ValueError()
        if set(p['id'] for p in value['panels']) != set(PANEL_IDS):
            raise ValueError()
        for panel in value['panels']:
            if set(panel) != {'id', 'visible', 'collapsed', 'wide'} or not all(type(panel[k]) is bool for k in ('visible', 'collapsed', 'wide')):
                raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ValueError('invalid_intel_dashboard_preferences') from None
    return copy.deepcopy(value)


def definitions(schema, string):
    return [
        ('commerce_intel_dashboard_get', '读取共享情报仪表盘布局、真实图层目录与地理参考；不采集或调用模型', schema()),
        ('commerce_intel_dashboard_update', '保存明确选择的图层、面板和中文阅读偏好；版本冲突不会覆盖其它界面',
         schema({'expected_revision': {'type': 'integer', 'minimum': 0}, 'preferences': {'type': 'object'}}, ['expected_revision', 'preferences'])),
    ]


class IntelDashboard:
    def __init__(self, core):
        self.core = core
        with core.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS intel_dashboard_preferences (id INTEGER PRIMARY KEY CHECK(id=1), revision INTEGER NOT NULL, document TEXT NOT NULL)')

    def get(self):
        with self.core.db() as db:
            row = db.execute('SELECT revision,document FROM intel_dashboard_preferences WHERE id=1').fetchone()
        return dict(revision=row[0] if row else 0, preferences=validate(json.loads(row[1])) if row else defaults(),
                    layers=catalog(), regions=REGIONS, references=REFERENCES, scope='shared_local_owner')

    def update(self, expected_revision, preferences):
        preferences = validate(preferences)
        if type(expected_revision) is not int or expected_revision < 0:
            raise ValueError('invalid_intel_dashboard_revision')
        with self.core.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT revision,document FROM intel_dashboard_preferences WHERE id=1').fetchone()
            if (row[0] if row else 0) != expected_revision:
                raise ValueError('intel_dashboard_conflict')
            if row and json.loads(row[1]) == preferences:
                return dict(revision=row[0], preferences=preferences, persisted=True)
            revision = expected_revision + 1
            db.execute('INSERT OR REPLACE INTO intel_dashboard_preferences VALUES (1,?,?)',
                       (revision, json.dumps(preferences, ensure_ascii=False, sort_keys=True)))
        return dict(revision=revision, preferences=preferences, persisted=True)
