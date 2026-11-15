"""Coalesced receipt discovery retains originals and requires a displayed group hash."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0]=[str(Path(__file__).resolve().parents[1]),str(Path(__file__).resolve().parent)]
import test_followups as fixture


class Groups(unittest.TestCase):
    setUp=fixture.Followups.setUp
    tearDown=fixture.Followups.tearDown
    targets=fixture.Followups.targets
    source=fixture.Followups.source
    create=fixture.Followups.create

    def twice(self):
        target=self.source();first=self.create(target,'first');self.app.followups.tick(at=fixture.NOW+61)
        second=self.create(target,'second',fixture.NOW+120);self.app.followups.tick(at=fixture.NOW+121)
        return first,second

    def test_same_bound_object_has_one_attention_notice_and_two_immutable_receipts(self):
        first,second=self.twice();items=self.app.attention.listing(include_followups=True)['items']
        self.assertEqual(len(items),1)
        self.assertEqual(items[0]['action']['id'],second['id'])
        self.assertEqual(items[0]['followup_count'],2)
        value=self.app.followups.get(first['id'])
        self.assertEqual(value['receipt_group']['count'],2)
        self.assertEqual(value['receipt_group']['latest']['id'],second['id'])
        self.assertEqual(len(self.app.followups.listing()['items']),2)
        with self.app.core.db() as db:self.assertEqual(db.execute('SELECT count(*) FROM followup_checks').fetchone()[0],2)

    def test_acknowledging_displayed_group_cannot_consume_a_new_unseen_receipt(self):
        first,second=self.twice();displayed=self.app.followups.get(second['id'])
        third=self.create(self.source(),'third',fixture.NOW+180);self.app.followups.tick(at=fixture.NOW+181)
        with self.assertRaisesRegex(ValueError,'followup_group_changed'):
            self.app.followups.ack(second['id'],displayed['revision'],displayed['receipt_group']['sha256'])
        self.assertTrue(all(v['state']=='checked'for v in self.app.followups.listing()['items']))
        latest=self.app.followups.get(third['id']);before=latest['receipt']
        self.app.followups.ack(third['id'],latest['revision'],latest['receipt_group']['sha256'])
        self.assertEqual(self.app.attention.listing(include_followups=True)['items'],[])
        self.assertEqual(self.app.followups.get(third['id'])['receipt'],before)
        self.assertTrue(all(v['state']=='acknowledged'for v in self.app.followups.listing()['items']))

    def test_a_source_binding_change_is_never_merged_with_the_previous_source(self):
        import followups
        first=self.create(self.source(),'old');self.app.followups.tick(at=fixture.NOW+61)
        with patch.dict(followups.SOURCES['usgs'],{'url':'https://example.invalid/new-synthetic-source'}):
            second=self.create(self.source(),'new',fixture.NOW+120);self.app.followups.tick(at=fixture.NOW+121)
            self.assertEqual(len(self.app.attention.listing(include_followups=True)['items']),2)
            self.assertFalse(self.app.followups.get(first['id'])['scope_current'])


if __name__=='__main__':unittest.main()
