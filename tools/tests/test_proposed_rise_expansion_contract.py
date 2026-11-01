"""Structural checks for a proposed fixture; no Core gameplay is executed."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2] / 'IRGS_Catalog'
FIXTURE = ROOT / 'evaluation/proposed_rise_expansion_v1'
PROFILE = ROOT / 'design/rise/proposed_reed_expansion_v1.json'


class ProposedRiseExpansionContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = json.loads(PROFILE.read_text(encoding='utf-8'))
        cls.actors = json.loads((FIXTURE / 'actor_inputs/cases.json').read_text(encoding='utf-8'))
        cls.oracle = json.loads((FIXTURE / 'evaluator_only/expectations.json').read_text(encoding='utf-8'))

    def test_proposal_and_source_boundaries(self):
        p = self.profile
        self.assertEqual(p['status'], 'proposed-unselected')
        self.assertFalse(p['runtime_adoption'])
        self.assertIn('not a historical rule', p['scope'])
        self.assertEqual(p['id'], self.actors['profile_id'])
        self.assertEqual(p['id'], self.oracle['profile_id'])
        self.assertEqual(self.oracle['classification'], 'evaluator-only')
        self.assertNotIn(self.oracle['marker'], json.dumps(self.actors))
        self.assertNotIn('fixtures', self.actors)
        self.assertTrue(all(set(c) == {'id', 'goal', 'actions'} for c in self.actors['cases']))

    def test_cases_are_complete_and_paired_without_actor_truth(self):
        cases = self.actors['cases']
        ids = [c['id'] for c in cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {'limit', 'concurrency', 'pause-complete', 'cancel',
                                    'refusal', 'valid-expansion', 'invalid-issuer',
                                    'recovery', 'retained-works'})
        self.assertEqual(set(ids), set(self.oracle['fixtures']))
        for case in cases:
            self.assertTrue(case['goal'])
            self.assertTrue(case['actions'])
            truth = self.oracle['fixtures'][case['id']]
            self.assertTrue(truth['setup'])
            self.assertTrue(truth['assertions'])
            self.assertNotIn(truth['setup'], json.dumps(case))
            for expected in truth['assertions']:
                self.assertNotIn(expected, json.dumps(case))

    def test_demonstration_values_are_coherent(self):
        values = self.profile['values']
        self.assertGreater(values['initial_allowance'], values['initial_completed_buildings'])
        self.assertEqual(values['initial_allowance'] - values['initial_completed_buildings'], 1)
        self.assertEqual(values['increment_on_accepted_grant'], 1)
        self.assertGreaterEqual(values['synthetic_initial_timber'], values['synthetic_timber_per_project'])
        self.assertEqual(values['request_fee'], 0)
        self.assertEqual(values['request_elapsed_seconds'], 0)


if __name__ == '__main__':
    unittest.main()
