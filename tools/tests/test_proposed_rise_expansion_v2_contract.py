"""Structural checks for revision 2 of a proposed, unselected design."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2] / 'IRGS_Catalog'
FIXTURE = ROOT / 'evaluation/proposed_rise_expansion_v2'
PROFILE = ROOT / 'design/rise/proposed_reed_expansion_v2.json'


class ProposedRiseExpansionV2Contract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = json.loads(PROFILE.read_text(encoding='utf-8'))
        cls.actors = json.loads((FIXTURE / 'actor_inputs/cases.json').read_text(encoding='utf-8'))
        cls.oracle = json.loads((FIXTURE / 'evaluator_only/expectations.json').read_text(encoding='utf-8'))

    def test_unselected_and_separate_actor_truth(self):
        self.assertEqual(self.profile['status'], 'proposed-unselected')
        self.assertFalse(self.profile['runtime_adoption'])
        self.assertEqual(self.profile['id'], self.actors['profile_id'])
        self.assertEqual(self.profile['id'], self.oracle['profile_id'])
        self.assertEqual(self.oracle['classification'], 'evaluator-only')
        self.assertNotIn(self.oracle['marker'], json.dumps(self.actors))
        self.assertTrue(all(set(c) == {'id', 'goal', 'actions'} for c in self.actors['cases']))

    def test_complete_distinct_cases_and_nonleaking_setup(self):
        cases = self.actors['cases']
        ids = [c['id'] for c in cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {'limit', 'concurrency', 'pause-complete', 'cancel', 'refusal',
                                    'valid-expansion', 'invalid-issuer', 'recovery',
                                    'retained-works', 'review-reuse'})
        self.assertEqual(set(ids), set(self.oracle['fixtures']))
        for case in cases:
            truth = self.oracle['fixtures'][case['id']]
            self.assertTrue(case['goal'] and case['actions'] and truth['setup'] and truth['assertions'])
            self.assertNotIn(truth['setup'], json.dumps(case))
            for item in truth['assertions']:
                self.assertNotIn(item, json.dumps(case))

    def test_proposed_values_and_open_contracts(self):
        p = self.profile
        v = p['values']
        self.assertEqual(v['initial_completed_buildings'], 0)
        self.assertEqual((v['initial_allowance'], v['increment_on_accepted_grant']), (2, 1))
        self.assertEqual((v['synthetic_initial_timber'], v['synthetic_timber_per_project']), (9, 3))
        self.assertEqual(set(p['unresolved_choices']), {'identity', 'authority', 'review',
                         'concurrency', 'resources', 'migration', 'disposition'})
        self.assertTrue(all(p['unresolved_choices'].values()))

    def test_deferred_conflicts_and_no_reservation_refund_are_recorded(self):
        f = self.oracle['fixtures']
        self.assertTrue(any('both may be deferred' in s for s in f['concurrency']['assertions']))
        self.assertTrue(any('without crediting stock' in s for s in f['cancel']['assertions']))
        self.assertTrue(any('consumed review' in s for s in f['review-reuse']['assertions']))
        self.assertIn('not a physical transfer', self.profile['material_accounting']['admission'])


if __name__ == '__main__':
    unittest.main()
