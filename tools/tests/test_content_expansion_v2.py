"""Optional campaign-neutral writing and planned story boundaries."""
import collections
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / 'IRGS_Catalog'
sys.path.insert(0, str(CATALOG))
import scripted_responses as responses


def fact(family, values=None):
    return {'actor_id': 'synthetic-person', 'snapshot_id': 'synthetic-snapshot',
            'source_ref': 'synthetic:' + family['id'],
            'source_kind': family['source_kind'], 'state': family['state'],
            'values': values if values is not None else {
                key: 1 if kind == 'integer' else 'example'
                for key, kind in family['slots'].items()}}


class OptionalWritingTests(unittest.TestCase):
    def setUp(self):
        self.original = responses.load_library()
        self.expanded = responses.load_library(CATALOG / 'responses/depot_v2/library.json')
        self.families = {f['id']: f for f in self.expanded['families']}

    def test_identity_counts_and_existing_content_are_preserved(self):
        original_bytes = (CATALOG / 'responses/depot_v1/library.json').read_bytes()
        self.assertEqual(hashlib.sha256(original_bytes).hexdigest(),
                         '8b397ae8cd72cf5ed59c330c0572e34922579726740edbeed9fca957044a6ae4')
        self.assertEqual(self.original['library_id'], 'irgs-response-depot-v1')
        self.assertEqual(self.expanded['library_id'], 'irgs-response-depot-v2')
        self.assertEqual(self.expanded['families'][:127], self.original['families'])
        self.assertEqual(self.expanded['recipes'][:32], self.original['recipes'])
        counts = collections.Counter()
        strings = []
        for family in self.expanded['families']:
            counts[family['channel']] += len(family['variants'])
            strings.extend(family['variants'])
        self.assertEqual(counts, {'system': 806, 'player_draft': 298})
        self.assertEqual(len(self.families), 140)
        self.assertEqual(len(self.expanded['recipes']), 39)
        self.assertEqual(len({' '.join(s.casefold().split()) for s in strings}), 1104)

    def test_new_variants_render_from_facts_across_four_settings(self):
        themes = [
            ('Chancellor', 'Royal Hall', 'review the petition'),
            ('Pathfinder', 'Moon Gate', 'read the runes'),
            ('Navigator', 'Orbital Dock', 'inspect the airlock'),
            ('Detective', 'City Archive', 'review evidence')]
        for person, place, task in themes:
            supplied = {'person_label': person, 'place_label': place,
                        'task_label': task, 'subject_label': task,
                        'record_text': 'No permission was granted.\\n{untrusted.literal}'}
            for family in self.expanded['families'][127:]:
                values = {key: supplied[key] for key in family['slots']}
                for index in range(len(family['variants'])):
                    with self.subTest(theme=place, family=family['id'], index=index):
                        result = responses.render_fragment(self.expanded, family['id'],
                                                           fact(family, values), variant=index)
                        self.assertTrue(result)
                        for value in values.values():
                            self.assertIn(value, result)

    def test_exact_committed_result_cannot_be_replaced(self):
        receipt = 'No goods changed hands.\\nThe task is not complete. {untrusted.literal}'
        context = fact(self.families['receipt.exact'], {'receipt_text': receipt})
        self.assertEqual(responses.render_fragment(self.expanded, 'receipt.exact', context), receipt)
        edited = copy.deepcopy(self.expanded)
        next(f for f in edited['families'] if f['id'] == 'receipt.exact')['variants'] = ['Done.']
        with self.assertRaisesRegex(ValueError, 'exact receipt'):
            responses.validate_library(edited)

    def test_scope_and_state_conflicts_still_fail(self):
        refusal = fact(self.families['record.refusal'], {'record_text': 'No.'})
        request = fact(self.families['record.request_received'], {'record_text': 'Please.'})
        for key in ('actor_id', 'snapshot_id'):
            other = copy.deepcopy(request)
            other[key] = 'different-scope'
            parts = [{'family_id': 'record.refusal', 'variant': 0, 'context': refusal},
                     {'family_id': 'record.request_received', 'variant': 0, 'context': other}]
            with self.subTest(scope=key), self.assertRaisesRegex(ValueError, 'actors or snapshots'):
                responses.compose(self.expanded, parts)
        request['source_ref'] = refusal['source_ref']
        parts = [{'family_id': 'record.refusal', 'variant': 0, 'context': refusal},
                 {'family_id': 'record.request_received', 'variant': 0, 'context': request}]
        with self.assertRaisesRegex(ValueError, 'Conflicting response states'):
            responses.compose(self.expanded, parts)

    def test_story_is_a_planned_unreleased_concept(self):
        portfolio = json.loads((CATALOG / 'data/campaign_portfolio.json').read_text(encoding='utf-8'))
        story = next(e for e in portfolio['entries'] if e['catalogue_id'] == 'SS-17')
        self.assertEqual(story['development_status'], 'planned')
        self.assertIs(story['availability']['release_approved'], False)
        self.assertIs(story['readiness']['full_campaign_ready'], False)
        self.assertIs(story['design_review']['runtime_certified'], False)
        draft = (CATALOG / 'content/short_stories/SS-17-pressure-falling-v1.md').read_text(encoding='utf-8')
        self.assertIn('original fictional writing draft', draft)
        self.assertIn('not a playable campaign', draft)


if __name__ == '__main__':
    unittest.main()
