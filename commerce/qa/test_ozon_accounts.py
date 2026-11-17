"""Temporary real Core/LiveConnections account switching; no provider calls."""
import importlib.util
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from commerce_core import Core
from live_connections import LiveConnections
from test_live_connections import batch

spec = importlib.util.find_spec('ozon_accounts')
if spec:
    from ozon_accounts import OzonAccounts
else:
    OzonAccounts = None


class OzonAccountTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.live = LiveConnections(Core(self.root/'db.sqlite'), self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def accounts(self):
        self.assertIsNotNone(OzonAccounts, 'Durable single-active Ozon account registry is missing')
        return OzonAccounts(self.live)

    def create(self, accounts, client='111111', key='synthetic-first-api-key', label='First'):
        return accounts.configure(dict(ozon_client_id=client, ozon_api_key=key,
            store_label=label, fulfillment_modes=['OGL']))

    def publish(self, kind='orders', posting='SYN-FIRST'):
        config = self.live.config()
        self.live._publish(config['connection_id'], kind, batch(kind,posting=posting), config, False)

    def test_feature_class_exists(self):
        self.accounts()

    def test_legacy_account_is_archived_before_replacement_and_snapshot_restored(self):
        self.live.configure(dict(ozon_client_id='111111',ozon_api_key='synthetic-first-api-key'))
        old = self.live.config(); self.publish()
        accounts = self.accounts(); before = accounts.listing(); first = before['active_account_id']
        self.create(accounts,'222222','synthetic-second-api-key','Second')
        current = accounts.listing(); self.assertEqual(len(current['accounts']),2)
        self.assertNotEqual(current['active_account_id'],first)
        result = accounts.activate(first,current['revision'],'switch-back')
        self.assertEqual(result['accounts']['active_account_id'],first)
        self.assertEqual(self.live.config()['connection_id'],old['connection_id'])
        self.assertEqual(self.live.order_rows()[0]['posting_number'],'SYN-FIRST')
        self.assertFalse(self.live.config()['orders_scope_confirmed'])

    def test_same_named_accounts_do_not_merge_or_mix_snapshots(self):
        accounts=self.accounts(); self.create(accounts,label='Same'); self.publish()
        first=accounts.listing()['active_account_id']; old=self.live.config()['connection_id']
        self.create(accounts,'222222','synthetic-second-api-key','Same')
        self.assertEqual(len(accounts.listing()['accounts']),2)
        self.assertNotEqual(self.live.config()['connection_id'],old)
        self.assertEqual(self.live.order_rows(),[])
        self.publish(posting='SYN-SECOND')
        accounts.activate(first,accounts.listing()['revision'],'first-again')
        self.assertEqual([r['posting_number']for r in self.live.order_rows()],['SYN-FIRST'])

    def test_readonly_listing_does_not_create_registry_or_mutate_legacy_config(self):
        self.live.configure(dict(ozon_client_id='111111',ozon_api_key='synthetic-first-api-key'))
        before=self.live.path.read_bytes(); accounts=self.accounts()
        value=accounts.listing();self.assertEqual(len(value['accounts']),1)
        self.assertEqual(before,self.live.path.read_bytes());self.assertFalse(accounts.path.exists())

    def test_public_results_and_errors_never_return_credentials(self):
        accounts=self.accounts();result=self.create(accounts)
        for value in (result,accounts.listing(),accounts.status()):
            text=json.dumps(value)
            for secret in ('111111','synthetic-first-api-key'):
                self.assertNotIn(secret,text)
        for account in accounts.listing()['accounts']:
            self.assertNotIn('ozon_client_id',account);self.assertNotIn('ozon_api_key',account)
        with self.assertRaisesRegex(ValueError,'ozon_account_not_found'):
            accounts.activate('a'*32,accounts.listing()['revision'],'missing')

    def test_switch_always_disables_automation_and_discards_review_attestations(self):
        accounts=self.accounts(); self.create(accounts); self.publish(); self.publish('stock')
        self.live.configure(dict(orders_scope_confirmed=True,stock_basis='present_minus_reserved',basis_confirmed=True))
        old=self.live.config();old.update(sync_enabled=True,notifications_enabled=True,
            feishu_test_verified=True,feishu_received_confirmed=True);self.live._save(old)
        first=accounts.listing()['active_account_id']
        self.create(accounts,'222222','synthetic-second-api-key','Second')
        accounts.activate(first,accounts.listing()['revision'],'back-no-trust')
        result=self.live.config()
        for flag in ('sync_enabled','notifications_enabled','orders_scope_confirmed','feishu_test_verified','feishu_received_confirmed'):
            self.assertFalse(result[flag])
        self.assertEqual(result['stock_basis'],'unconfirmed')
        self.assertNotIn('orders_scope_review_snapshot',result)
        self.assertNotIn('basis_review_snapshot',result)

    def test_key_rotation_preserves_account_and_snapshot_ownership_but_resets_review(self):
        accounts=self.accounts();self.create(accounts);self.publish()
        self.live.configure({'orders_scope_confirmed':True})
        first=accounts.listing()['active_account_id'];connection=self.live.config()['connection_id']
        accounts.configure({'ozon_api_key':'synthetic-rotated-api-key'})
        self.assertEqual(accounts.listing()['active_account_id'],first)
        self.assertEqual(self.live.config()['connection_id'],connection)
        self.assertFalse(self.live.config()['orders_scope_confirmed'])
        self.assertEqual(self.live.config()['ozon_api_key'],'synthetic-rotated-api-key')
        self.assertEqual(len(accounts.listing()['accounts']),1)

    def test_old_guide_configuration_and_blank_secrets_still_work(self):
        accounts=self.accounts();self.create(accounts);self.publish()
        result=accounts.configure({'ozon_api_key':'','orders_scope_confirmed':True})
        self.assertTrue(result['orders_scope_confirmed'])
        self.assertEqual(self.live.config()['ozon_api_key'],'synthetic-first-api-key')

    def test_activate_requires_fresh_revision_and_replay_does_not_reswitch(self):
        accounts=self.accounts();self.create(accounts);first=accounts.listing()['active_account_id']
        stale=accounts.listing()['revision'];self.create(accounts,'222222','synthetic-second-api-key','Second')
        second=accounts.listing()['active_account_id']
        with self.assertRaisesRegex(ValueError,'ozon_accounts_revision_changed'):
            accounts.activate(first,stale,'old-revision')
        rev=accounts.listing()['revision'];accounts.activate(first,rev,'one-switch')
        accounts.activate(second,accounts.listing()['revision'],'switch-two')
        result=accounts.activate(first,rev,'one-switch')
        self.assertEqual(result['accounts']['active_account_id'],second)
        self.assertTrue(result['accounts']['idempotent_replay'])
        with self.assertRaisesRegex(ValueError,'ozon_accounts_idempotency_conflict'):
            accounts.activate(second,rev,'one-switch')

    def test_busy_sync_and_sending_message_refuse_mutation(self):
        accounts=self.accounts();self.create(accounts);before=self.live.path.read_bytes()
        self.live.lock.acquire()
        try:
            with self.assertRaisesRegex(ValueError,'ozon_account_busy'):
                self.create(accounts,'222222','synthetic-second-api-key','Second')
        finally:self.live.lock.release()
        self.assertEqual(self.live.path.read_bytes(),before)
        with self.live.core.db()as db:
            db.execute('INSERT INTO live_outbox VALUES (?,?,?,?,?,?,?,?,?)',('syn','syn','conn','channel','sending','synthetic','','',None))
        with self.assertRaisesRegex(ValueError,'ozon_account_busy'):
            self.create(accounts,'222222','synthetic-second-api-key','Second')

    def test_validation_failure_rolls_back_live_and_registry(self):
        accounts=self.accounts();self.create(accounts)
        before=self.live.path.read_bytes();registry=accounts.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'invalid_client_id'):
            accounts.configure({'ozon_client_id':'not-a-client','ozon_api_key':'synthetic-invalid-account'})
        self.assertEqual(self.live.path.read_bytes(),before)
        self.assertEqual(accounts.path.read_bytes(),registry)
        self.assertFalse(accounts.journal.exists())

    def test_private_files_permissions_and_corruption_fail_closed(self):
        accounts=self.accounts();self.create(accounts)
        self.assertEqual(stat.S_IMODE(accounts.directory.stat().st_mode),0o700)
        self.assertEqual(stat.S_IMODE(accounts.path.stat().st_mode),0o600)
        before=self.live.path.read_bytes();accounts.path.write_text('{broken')
        with self.assertRaisesRegex(ValueError,'ozon_accounts_registry_invalid'):accounts.listing()
        self.assertEqual(self.live.path.read_bytes(),before)

    def test_same_active_activation_is_noop_without_erasing_existing_reviews(self):
        accounts=self.accounts();self.create(accounts);self.publish()
        self.live.configure({'orders_scope_confirmed':True})
        active=accounts.listing()['active_account_id'];revision=accounts.listing()['revision']
        accounts.activate(active,revision,'same-active')
        self.assertTrue(self.live.config()['orders_scope_confirmed'])

    def test_recovery_of_incomplete_change_restores_previous_config(self):
        accounts=self.accounts();self.create(accounts)
        before=self.live.config();reg=json.loads(accounts.path.read_text())
        # Synthetic interrupted intent: no fully prepared after-state exists.
        accounts.journal.write_text(json.dumps(dict(schema='ozon-account-intent-v1',
            before_config=before,before_registry=reg,after_config=None,after_registry=None)))
        changed={**before,'ozon_client_id':'222222','ozon_api_key':'synthetic-incomplete-key'}
        self.live._save(changed)
        with self.assertRaisesRegex(ValueError,'ozon_accounts_recovery_required'):accounts.listing()
        accounts.recover()
        self.assertEqual(self.live.config(),before)
        self.assertFalse(accounts.journal.exists())

    def test_source_registry_symlink_is_refused(self):
        accounts=self.accounts();self.create(accounts)
        copy=accounts.directory/'synthetic-copy.json';copy.write_bytes(accounts.path.read_bytes())
        accounts.path.unlink();accounts.path.symlink_to(copy)
        with self.assertRaisesRegex(ValueError,'ozon_accounts_registry_invalid'):accounts.listing()

    def test_new_account_cannot_inherit_previous_key_or_notification_target(self):
        accounts=self.accounts();self.create(accounts)
        original=self.live.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'invalid_ozon_api_key'):
            accounts.configure({'ozon_client_id':'222222','ozon_api_key':''})
        self.assertEqual(self.live.path.read_bytes(),original)
        old=self.live.config();old.update(feishu_webhook='synthetic-old-channel',
            feishu_signing_secret='synthetic-old-signature',feishu_target_label='Old channel',
            feishu_received_confirmed=True);self.live._save(old)
        self.create(accounts,'222222','synthetic-second-api-key','Second')
        new=self.live.config()
        self.assertFalse(new.get('feishu_webhook'));self.assertFalse(new.get('feishu_signing_secret'))
        self.assertFalse(new['feishu_received_confirmed']);self.assertEqual(new['feishu_target_label'],'')

    def test_prepared_journal_recovery_finishes_exact_stored_switch(self):
        accounts=self.accounts();self.create(accounts)
        before=self.live.config();oldreg=json.loads(accounts.path.read_text())
        self.create(accounts,'222222','synthetic-second-api-key','Second')
        after=self.live.config();newreg=json.loads(accounts.path.read_text())
        accounts.journal.write_text(json.dumps(dict(schema='ozon-account-intent-v1',
            before_config=before,before_registry=oldreg,after_config=after,after_registry=newreg)))
        self.live._save(before);accounts._write(accounts.path,oldreg)
        accounts.recover()
        self.assertEqual(self.live.config(),after)
        self.assertEqual(accounts.listing()['active_account_id'],newreg['active_account_id'])

    def test_registry_write_failure_rolls_back_and_retains_both_accounts(self):
        accounts=self.accounts();self.create(accounts)
        self.create(accounts,'222222','synthetic-second-api-key','Second')
        before=self.live.path.read_bytes();registry=accounts.path.read_bytes()
        first=next(r['account_id']for r in accounts.listing()['accounts']if not r['active'])
        write=accounts._write;failed=[]
        def one_failure(path,value):
            if path==accounts.path and not failed:
                failed.append(True);raise OSError('synthetic write failure')
            return write(path,value)
        with patch.object(accounts,'_write',side_effect=one_failure):
            with self.assertRaisesRegex(OSError,'synthetic write failure'):
                accounts.activate(first,accounts.listing()['revision'],'switch-fails')
        self.assertEqual(before,self.live.path.read_bytes());self.assertEqual(registry,accounts.path.read_bytes())
        self.assertEqual(len(accounts.listing()['accounts']),2)


if __name__=='__main__':unittest.main()
