"""Recovery proof uses independent copies and never instantiates the service."""
from pathlib import Path
import hashlib
import json
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from database_recovery import verify_recovery,fingerprint


class DatabaseRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.state=Path(self.tmp.name);self.path=self.state/'commerce.sqlite'
        with sqlite3.connect(self.path)as db:
            db.execute('CREATE TABLE tasks(id INTEGER PRIMARY KEY AUTOINCREMENT,status TEXT,payload BLOB)')
            db.execute('INSERT INTO tasks(status,payload) VALUES (?,?)',('running',b'private-fixture-value'))
            db.execute('CREATE TABLE numeric_values(n REAL,t TEXT,i INTEGER)');db.executemany('INSERT INTO numeric_values VALUES (?,?,?)',[(1.25,'1',1),(-0.0,'',None)])
    def tearDown(self):self.tmp.cleanup()

    def test_round_trip_integrity_types_and_private_permissions(self):
        before=hashlib.sha256(self.path.read_bytes()).hexdigest();result=verify_recovery(self.state);self.assertEqual(result['status'],'passed')
        self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest());self.assertFalse(result['details']['live_database_restored']);self.assertFalse(result['details']['workers_started_or_stopped'])
        for path in result['report'].parent.iterdir():self.assertEqual(path.stat().st_mode&0o777,0o600)
        self.assertNotIn('private-fixture-value',result['report'].read_text())
        with sqlite3.connect(result['report'].parent/'restored.sqlite')as db:self.assertEqual(db.execute('SELECT status FROM tasks').fetchone()[0],'running')

    def test_live_writer_is_not_stopped_or_rolled_back(self):
        stop=threading.Event();count=[]
        def write():
            with sqlite3.connect(self.path,timeout=5)as db:
                while not stop.is_set():
                    db.execute('INSERT INTO tasks(status) VALUES (?)',('live-writer',));db.commit();count.append(1);time.sleep(.002)
        writer=threading.Thread(target=write);writer.start()
        try:
            while not count:time.sleep(.005)
            result=verify_recovery(self.state);self.assertEqual(result['status'],'passed');self.assertTrue(writer.is_alive());self.assertGreater(len(count),0)
        finally:stop.set();writer.join(5)

    def test_failed_verification_preserves_failed_copy_and_source(self):
        before=hashlib.sha256(self.path.read_bytes()).hexdigest()
        with patch('database_recovery.fingerprint',side_effect=ValueError('database_restore_fingerprint_mismatch')):result=verify_recovery(self.state)
        self.assertEqual(result['status'],'failed');self.assertTrue((result['report'].parent/'backup.sqlite').exists());self.assertEqual(before,hashlib.sha256(self.path.read_bytes()).hexdigest())

    def test_limits_symlinks_and_source_missing_are_safe(self):
        self.assertEqual(verify_recovery(self.state,row_limit=0)['status'],'failed')
        other=self.state/'other';other.mkdir();self.path.unlink();self.path.symlink_to(other/'outside')
        with self.assertRaisesRegex(ValueError,'source_unavailable'):verify_recovery(self.state)
        self.path.unlink()
        with self.assertRaises(ValueError):verify_recovery(self.state)

    def test_restore_change_is_detected_by_schema_or_row_hash(self):
        original=fingerprint;calls=[]
        def changed(db,limit):
            r=original(db,limit);calls.append(1)
            if len(calls)==2:r['total_rows']+=1
            return r
        with patch('database_recovery.fingerprint',side_effect=changed):result=verify_recovery(self.state)
        self.assertEqual(result['status'],'failed');self.assertEqual(result['details']['code'],'database_restore_fingerprint_mismatch')

if __name__=='__main__':unittest.main()
