"""Explicit recovery may retry failed reads, without replaying confirmed models."""
import unittest
import test_market_research_contract as fixtures


class CaptureRecovery(unittest.TestCase):
    def test_all_failed_sources_can_be_retried_on_original_task_without_replanning(self):
        fixture=fixtures.MarketResearchContract();fixture.setUp()
        self.addCleanup(fixture.tearDown)
        sent=fixture.send_research()
        def timeout(*args):raise ValueError('market_research_source_timeout')
        fixture.execute(capture=timeout)
        failed=fixture.app.market_research.get(sent['research_job']['task_id'])
        self.assertEqual(failed['status'],'failed')
        self.assertEqual(fixture.executed['planning'],1)
        args=(failed['task_id'],failed['revision'],'explicit-retry-failed-reads')
        resumed=fixture.app.market_research.resume(*args)
        self.assertEqual(fixture.app.market_research.resume(*args),resumed)
        fixture.execute()
        final=fixture.app.market_research.get(failed['task_id'])
        self.assertEqual(final['status'],'partial')
        self.assertEqual(final['source_count'],1)
        self.assertEqual(final['candidate_count'],1)
        self.assertEqual(fixture.executed['planning'],1)
        self.assertEqual(fixture.task_count(),1)
        with fixture.app.core.db() as db:
            internal=fixture.app.market_research._load(db,failed['task_id'])
        self.assertEqual(len(internal['_collection_failures']),1)
        self.assertEqual(internal['_collection_failures'][0]['sources'],failed['sources'])


if __name__=='__main__':unittest.main()
