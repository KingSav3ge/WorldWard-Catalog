"""Independent ordinary journeys over real HTTP; run this file in a fresh process."""
import argparse
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / 'IRGS_Catalog/evaluation/sustained_ordinary_v1'
ENGINE_SHA = 'ecca8094a2d2cdb8a11e018a085487288b26e88d'
APP_SHA = 'c04ba5524ae95316c7e826fc63085a4916d7dd67'
CATALOG_BASE = 'a18cb48928da25d40d057a182c69f71ef149ce80'
REPORTS = {}
SOURCE_SELECTION = {}

# Each session is a new interpreter and App server using only the same
# synthetic save directory. No campaign state is seeded by this harness.
HOST = r"""
import importlib
import json
import os
from pathlib import Path
import socket
import sys
from unittest.mock import patch
app, engine, catalog, folder, ready = map(Path, sys.argv[1:])
os.environ['IRGS_ENGINE_ROOT'] = str(engine / 'IRGS_3_3')
os.environ['IRGS_CATALOG_ROOT'] = str(catalog / 'IRGS_Catalog')
sys.path[:0] = [str(app / 'IRGS_Web'), str(engine / 'IRGS_3_3/runtime')]
for name, source in [('server', app), ('core_world', engine), ('solo_provider', engine),
                     ('openai_proposals', engine)]:
    module = importlib.import_module(name)
    if not Path(module.__file__).resolve().is_relative_to(source.resolve()):
        raise RuntimeError('Wrong imported consumer source: ' + name)
counter = folder / 'blocked-provider-calls.json'
if not counter.exists():
    counter.write_text('0')
def blocked(*args, **kwargs):
    counter.write_text(str(int(counter.read_text()) + 1))
    raise AssertionError('This synthetic journey forbids provider calls')
real_connect = socket.socket.connect
def local_only(sock, address):
    if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', '::1', 'localhost'):
        raise AssertionError('External network is not authorized')
    return real_connect(sock, address)
with patch('solo_provider.CapabilityBroker.dispatch', side_effect=blocked), \
     patch('openai_proposals.OpenAIProposalTransport.__call__', side_effect=blocked), \
     patch('socket.socket.connect', local_only):
    from server import make_server
    server = make_server(0, folder / 'saves', reference_config=folder / 'absent-reference.json',
        reference_cache=folder / 'cache', solo_configuration=None)
    ready.write_text(json.dumps({'port': server.server_port}))
    try:
        server.serve_forever()
    finally:
        server.server_close()
"""


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


def source_binding():
    global SOURCE_SELECTION
    sources = {}
    for label, variable, sha in (
            ('engine', 'IRGS_SUSTAINED_ENGINE_SOURCE', ENGINE_SHA),
            ('app', 'IRGS_SUSTAINED_APP_SOURCE', APP_SHA),
            ('catalog', 'IRGS_SUSTAINED_CATALOG_SOURCE', os.environ.get('IRGS_SUSTAINED_CATALOG_COMMIT'))):
        path = os.environ.get(variable)
        if not path or not sha or not re.fullmatch(r'[0-9a-f]{40}', sha):
            raise RuntimeError('Exact source path and commit are required for ' + label)
        root = Path(path).resolve()
        if label == 'catalog' and root != ROOT:
            raise RuntimeError('Run the consumer from the selected Catalog checkout')
        if git(root, 'rev-parse', 'HEAD') != sha or git(root, 'status', '--porcelain'):
            raise RuntimeError('Source must be exact and clean: ' + label)
        sources[label] = root
    for name, expected in (('Engine', ENGINE_SHA), ('Catalog', CATALOG_BASE)):
        if git(sources['app'], 'rev-parse', 'HEAD:' + name) != expected:
            raise RuntimeError('Unexpected App committed gitlink: ' + name)
    manifest = json.loads((FIXTURE / 'manifest.json').read_text(encoding='utf-8'))
    selected = manifest['selection']
    if (selected['engine'], selected['app'], selected['catalog_base'],
            selected['app_engine_pin'], selected['app_catalog_pin']) != (
            ENGINE_SHA, APP_SHA, CATALOG_BASE, ENGINE_SHA, CATALOG_BASE):
        raise RuntimeError('Wrong sustained-journey selection')
    if set(manifest['files_sha256']) != {'actor_inputs/cases.json', 'evaluator_only/expectations.json', 'README.md'}:
        raise RuntimeError('Incomplete fixture binding')
    for path, expected in manifest['files_sha256'].items():
        if hashlib.sha256((FIXTURE / path).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Changed selected fixture: ' + path)
    SOURCE_SELECTION = {'engine': ENGINE_SHA, 'app': APP_SHA,
        'catalog': git(ROOT, 'rev-parse', 'HEAD'), 'catalog_base': CATALOG_BASE,
        'app_engine_pin': ENGINE_SHA, 'app_catalog_pin': CATALOG_BASE,
        'engine_override': False, 'catalog_override': True}
    return sources


class SustainedOrdinaryConsumers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = source_binding()
        cls.inputs = json.loads((FIXTURE / 'actor_inputs/cases.json').read_text(encoding='utf-8'))
        cls.oracle = json.loads((FIXTURE / 'evaluator_only/expectations.json').read_text(encoding='utf-8'))
        if cls.oracle['classification'] != 'evaluator-only' or cls.oracle['marker'] in json.dumps(cls.inputs):
            raise RuntimeError('Actor/evaluator separation failed')
        os.environ['IRGS_ENGINE_ROOT'] = str(cls.sources['engine'] / 'IRGS_3_3')
        os.environ['IRGS_CATALOG_ROOT'] = str(ROOT / 'IRGS_Catalog')
        engine = cls.sources['engine'] / 'IRGS_3_3/runtime'
        sys.path.insert(0, str(engine))
        for name in ('core_world', 'offline_responses'):
            module = importlib.import_module(name)
            if not Path(module.__file__).resolve().is_relative_to(engine):
                raise RuntimeError('Wrong evaluator import; use a fresh Python process')
            setattr(cls, name, module)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='worldward-sustained-ordinary-')
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.session = 0
        self.child = None
        self.log = None
        self.results = []
        self.evaluator_time_trace = []
        self.addCleanup(self.stop)
        self.start()

    def start(self):
        self.session += 1
        ready = self.folder / ('session-' + str(self.session) + '.json')
        self.log = (self.folder / ('session-' + str(self.session) + '.log')).open('wb')
        self.child = subprocess.Popen([sys.executable, '-B', '-u', '-c', HOST,
            str(self.sources['app']), str(self.sources['engine']), str(ROOT), str(self.folder), str(ready)],
            cwd=self.sources['app'], stdout=self.log, stderr=self.log)
        deadline = time.monotonic() + 25
        while not ready.exists():
            if self.child.poll() is not None or time.monotonic() >= deadline:
                self.log.flush()
                detail = (self.folder / ('session-' + str(self.session) + '.log')).read_text(errors='replace')[-2000:]
                raise RuntimeError('Synthetic App host did not become ready: ' + detail)
            time.sleep(0.05)
        self.url = 'http://127.0.0.1:' + str(json.loads(ready.read_text())['port'])
        self.token = ''
        self.token = self.ok('/api/campaigns')['token']
        self.assertEqual(int((self.folder / 'blocked-provider-calls.json').read_text()), 0)

    def stop(self):
        if self.child is not None:
            if self.child.poll() is None:
                self.child.terminate()
                try:
                    self.child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.child.kill()
                    self.child.wait(timeout=5)
            self.child = None
        if self.log is not None:
            self.log.close()
            self.log = None

    def restart(self, key):
        saved = self.save_path(key).read_bytes()
        self.stop()
        self.start()
        self.assertEqual(self.save_path(key).read_bytes(), saved)
        self.view(key)  # Normal reload must not reseed the world.
        self.assertEqual(self.save_path(key).read_bytes(), saved)

    def http(self, path, body=None, *, discard_body=False):
        if not path.startswith('/api/'):
            raise ValueError('Only this synthetic local API is allowed')
        headers = {'X-IRGS-Token': self.token}
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = Request(self.url + path, data=None if body is None else json.dumps(body).encode(), headers=headers)
        try:
            with urlopen(request, timeout=20) as response:
                code = response.status
                payload = None if discard_body else json.load(response)
        except HTTPError as error:
            code, payload = error.code, json.load(error)
        if payload is not None:
            self.assertNotIn(self.oracle['marker'], json.dumps(payload))
        return code, payload

    def ok(self, path, body=None):
        code, payload = self.http(path, body)
        self.assertEqual(code, 200, payload)
        return payload

    def save_path(self, key):
        self.assertRegex(key, r'^[0-9a-f]{32}$')
        return self.folder / 'saves' / (key + '.json')

    def state(self, key):
        return json.loads(self.save_path(key).read_text(encoding='utf-8'))['state']

    def view(self, key):
        return self.ok('/api/playthrough/' + key)

    def create(self, context):
        case = self.inputs[context]
        self.assertFalse(list((self.folder / 'saves').glob('*.json')))
        if context == 'rise':
            templates = self.ok('/api/rise/templates')
            # Inspect the published template response, rather than adding a campaign card.
            template = next(t for t in templates['templates'] if t['id'] == case['template_id'])
            self.assertTrue(template['ready'])
            reviewed = self.ok('/api/rise/preview', {'choices': case['choices']})
            body = {'name': 'Synthetic sustained Rise', 'choices': case['choices'],
                    'review_digest': reviewed['review_digest'], 'request_id': 'sustained-create-rise'}
            endpoint = '/api/rise/create'
        else:
            entry = self.ok('/api/historical-entry/' + case['entry_id'])
            fields = {name: case[name] for name in ('profile_id', 'scenario_id', 'entry_id')}
            fields['snapshot_sha256'] = entry['snapshot_sha256']
            options = self.ok('/api/starting-options?' + urlencode(fields))
            selected = next(o for o in options['playable_openings'] if o['id'] == case['opening_id'])
            self.assertTrue(selected['fictional'])
            self.assertEqual(options['default_scenario_id'], case['starting_scenario_id'])
            reviewed = self.ok('/api/starting-preview?' + urlencode({**fields,
                'selection_digest': options['selection_digest'], 'starting_scenario_id': case['starting_scenario_id'],
                'character_kind': 'new', 'species': 'human', 'opening_id': case['opening_id']}))
            self.assertEqual(reviewed['status'], 'supported_slice')
            body = {**fields, 'name': 'Synthetic sustained courier', 'character': case['character'],
                'starting_scenario_id': case['starting_scenario_id'], 'selection_digest': options['selection_digest'],
                'request_id': 'sustained-create-quay'}
            endpoint = '/api/create'
        created = self.ok(endpoint, body)
        key = created['id']
        before = self.save_path(key).read_bytes()
        self.assertEqual(self.ok(endpoint, body)['id'], key)
        self.assertEqual(self.save_path(key).read_bytes(), before)
        self.assertEqual(self.state(key)['binding']['campaign_profile'], case['profile_id'])
        self.assertEqual(self.state(key)['binding']['genre_id'], 'settlement' if context == 'rise' else 'military')
        if context == 'quay':
            self.assertEqual(self.state(key)['scene_rules']['id'], case['opening_id'])
        return key, self.view(key)['actor_id']

    def prepare(self, key, actor, action):
        view = self.view(key)
        control = view['intent_control']
        cap = next((c for c in control['capabilities'] if c['action'].get('action_id') == action['action']), None)
        self.assertIsNotNone(cap, 'Missing published action: ' + action['action'])
        body = {'id': key, 'actor': actor, 'revision': view['revision'], 'view_token': control['view_token'],
                'request_id': 'sustained-' + action['id'], 'intention': action['words'],
                'capability_id': cap['capability_id']}
        before = self.save_path(key).read_bytes()
        review = self.ok('/api/intent/prepare', body)
        self.assertEqual(review['intention'], action['words'])
        self.assertEqual(review['capability']['action']['action_id'], action['action'])
        self.assertEqual(self.save_path(key).read_bytes(), before)
        request = {name: body[name] for name in ('id', 'actor', 'request_id')}
        self.assertEqual(self.http('/api/intent/execute', {**request, 'explicitly_accepted': False})[0], 400)
        self.assertEqual(self.save_path(key).read_bytes(), before)
        return request

    def check_receipt(self, key, actor, result):
        self.assertEqual(result['actor'], actor)
        self.assertIn(result['status'], ('completed_successfully', 'completed_unsuccessfully'))
        event = result['receipt']['event_id']
        world = self.core_world.CoreWorld(state=self.state(key))
        facts = self.offline_responses.receipt_facts(world, actor, event)
        self.assertEqual(result['outcome']['summary'], facts['literal_text'])
        self.assertTrue(result['presentation']['text'].startswith(facts['literal_text']))
        self.assertEqual(result['presentation']['source_ref'], event)
        self.assertEqual(result['presentation']['render_usage'], {'provider_calls': 0, 'model_tokens': 0})

    def check_evaluator_time(self, request, action, before, after, public, *, rejected=False):
        """Check fixture time from Core state; never fill an actor receipt field."""
        left, right = before['elapsed_time'], after['elapsed_time']
        self.assertEqual(left['axis'], right['axis'])
        self.assertIs(type(left['seconds']), int)
        self.assertIs(type(right['seconds']), int)
        delta = right['seconds'] - left['seconds']
        self.assertGreaterEqual(delta, 0)
        self.assertEqual(after['campaign_time'], before['campaign_time'])
        if rejected:
            self.assertEqual(delta, 0)
        elif before['binding']['campaign_profile'] == 'rise':
            # The inspected shared settlement adapter supplies no action span.
            # Null is retained; it does not imply that the Core advanced by zero.
            self.assertIsNone(public['elapsed_time'])
            if action['action'] == 'wait_hour':
                model = before['settlement_model']
                candidates = [left['seconds'] + 3600, before['provision']['next_at']]
                candidates.extend(left['seconds'] + p['duration'] - p['worked']
                    for p in before['projects'].values() if p['status'] == 'active')
                candidates.extend(m['arrive_at'] for m in before['migrations'].values()
                                  if m['status'] == 'transit')
                self.assertLessEqual(3600, model['max_advance_seconds'])
                self.assertEqual(right['seconds'], min(candidates))
                self.assertGreater(delta, 0)
            elif action['action'] in ('walk_clearing', 'walk_commons'):
                self.assertEqual(delta, before['settlement_model']['travel_seconds'])
            else:
                self.assertEqual(delta, 0)
        else:
            duration = before['scene_rules']['actions'][action['action']]['duration_seconds']
            self.assertEqual(delta, duration)
            packet = public['elapsed_time']
            self.assertIsInstance(packet, dict)
            self.assertEqual(packet['axis'], left['axis'])
            self.assertEqual(packet['before_seconds'], left['seconds'])
            self.assertEqual(packet['after_seconds'], right['seconds'])
            self.assertEqual(packet['seconds'], delta)
        self.evaluator_time_trace.append({
            'classification': 'evaluator-only', 'request_id': request['request_id'],
            'action': action['action'], 'rejected_no_effects': rejected,
            'axis': left['axis'], 'before_seconds': left['seconds'], 'after_seconds': right['seconds'],
            'actual_delta_seconds': delta, 'public_elapsed_field_present': 'elapsed_time' in public,
            'public_elapsed_time': copy.deepcopy(public.get('elapsed_time')),
            'public_value_changed_by_consumer': False})

    def act(self, key, actor, action, *, reject=False, discard_body=False):
        request = self.prepare(key, actor, action)
        before = self.save_path(key).read_bytes()
        before_state = json.loads(before)['state']
        code, result = self.http('/api/intent/execute', {**request, 'explicitly_accepted': True},
                                 discard_body=discard_body)
        if reject:
            self.assertEqual(code, 400, result)
            self.assertEqual(self.save_path(key).read_bytes(), before)
            self.check_evaluator_time(request, action, before_state, self.state(key), result, rejected=True)
            return request, result
        self.assertEqual(code, 200, result)
        # The evaluator reads the actual durable record; it does not write it.
        saved = json.loads(self.save_path(key).read_text(encoding='utf-8'))['gameplay_requests'][request['request_id']]['result']
        if not discard_body:
            self.assertEqual(result, saved)
        self.assertEqual(saved['declaration'], action['words'])
        self.check_evaluator_time(request, action, before_state, self.state(key), saved)
        self.check_receipt(key, actor, saved)
        self.results.append((request, saved))
        return request, saved

    def recover_all(self, key, actor):
        before = self.save_path(key).read_bytes()
        for request, original in self.results:
            self.assertEqual(self.ok('/api/action-result/' + key + '/' + request['request_id'] +
                                     '?actor_id=' + actor), original)
            self.assertEqual(self.ok('/api/intent/execute', {**request, 'explicitly_accepted': True}), original)
        self.assertEqual(self.save_path(key).read_bytes(), before)
        if self.results:
            other = {**self.results[0][0], 'actor': 'oren' if actor == 'founder' else 'FICTIONAL-QUAY-CONTACT',
                     'explicitly_accepted': True}
            self.assertEqual(self.http('/api/intent/execute', other)[0], 403)
            self.assertEqual(self.save_path(key).read_bytes(), before)

    def restore_fence(self, key, actor, probe):
        request = self.prepare(key, actor, probe)
        before = self.save_path(key).read_bytes()
        revision = self.view(key)['revision']
        self.ok('/api/delete', {'id': key, 'revision': revision})
        self.ok('/api/restore', {'id': key, 'revision': revision})
        self.assertEqual(self.save_path(key).read_bytes(), before)
        self.assertEqual(self.http('/api/intent/execute', {**request, 'explicitly_accepted': True})[0], 400)
        self.assertEqual(self.save_path(key).read_bytes(), before)
        self.recover_all(key, actor)
        # Re-review the same voluntary inspection under a new request identity.
        # Actual further play after restore must not reseed or reset the world.
        fresh = {**probe, 'id': 'after-restore-' + probe['id']}
        _, result = self.act(key, actor, fresh)
        self.assertEqual(self.state(key)['stocks'], json.loads(before)['state']['stocks'])
        self.recover_all(key, actor)
        return result

    def evidence(self, context, **observed):
        provider_calls = int((self.folder / 'blocked-provider-calls.json').read_text())
        self.assertEqual(provider_calls, 0)
        self.assertEqual(self.session, 3)
        received_actions = [c['action'].get('action_id') for c in self.view(self.results[0][0]['id'])['intent_control']['capabilities']]
        REPORTS[context] = {'status': 'bounded_journey_passed', 'sessions': self.session,
            'context_selection': {name: self.inputs[context][name] for name in
                ('profile_id', 'template_id', 'scenario_id', 'entry_id', 'starting_scenario_id', 'opening_id')
                if name in self.inputs[context]},
            'final_received_action_ids': received_actions,
            'separate_server_processes': True, 'normal_reviewed_creation': True,
            'hidden_state_written_by_harness': False, 'provider_calls': provider_calls,
            'exact_original_retry': True, 'unaccepted_restore_fenced': True,
            'further_normal_play_after_restore': True,
            'evaluator_time_trace': self.evaluator_time_trace,
            'receipt_time_policy': 'Actor elapsed_time null is preserved; evaluator Core time is separate.',
            'receipt_matching': 'actor-scoped committed literal compared with actual local presentation',
            'semantic_quality_verified': False, 'live_provider_quality_verified': False,
            'discarded_response': 'One accepted response body was deliberately not read; recovered from durable result.',
            'receipts': [{'request_id': request['request_id'], 'event_id': value['receipt']['event_id'],
                         'status': value['status'], 'elapsed_time': value['elapsed_time'],
                         'literal': value['outcome']['summary']} for request, value in self.results],
            'observed': observed}

    def test_rise_three_sessions_permission_agency_work_and_finite_provision(self):
        key, actor = self.create('rise')
        initial_calendar = copy.deepcopy(self.state(key)['campaign_time'])
        phases = self.inputs['rise']['sessions']
        expected = self.oracle['rise']
        early = None
        for action in phases[0]:
            request, result = self.act(key, actor, action,
                reject=action['id'] in expected['rejected_requests'],
                discard_body=action['id'] == expected['refusal_request'])
            state = self.state(key)
            if action['id'] == 'request-grant':
                self.assertEqual(state['grants']['founding']['status'], 'offered')
            if action['id'] == 'accept-grant':
                self.assertEqual(state['grants']['founding']['status'], 'accepted')
            if action['id'] == expected['refusal_request']:
                early = result
                self.assertIn(expected['refusal_text'], result['outcome']['summary'].lower())
                self.assertNotIn('oren-move', state['migrations'])
                self.assertEqual(state['elapsed_time']['seconds'], expected['early_seconds'])
                self.assertEqual(state['stocks']['founder-home']['timber'], 6)
                self.assertEqual(state['stocks']['oren-home']['timber'], 3)
        self.restart(key)
        self.recover_all(key, actor)
        for action in phases[1]:
            _, result = self.act(key, actor, action)
            state = self.state(key)
            if action['id'] == 'wait-repair':
                self.assertEqual(state['elapsed_time']['seconds'], expected['after_repair_seconds'])
                self.assertEqual(state['projects']['oren-repair']['status'], 'complete')
            if action['id'] == 'invite-later':
                self.assertIn(expected['agreement_text'], result['outcome']['summary'].lower())
                self.assertEqual(state['migrations']['oren-move']['status'], 'agreed')
            if action['id'] == 'departure':
                self.assertEqual(state['migrations']['oren-move']['status'], 'transit')
                self.assertNotIn('oren-home', state['settlements']['camp']['households'])
            if action['id'] == 'wait-arrival':
                self.assertEqual(state['elapsed_time']['seconds'], expected['arrival_seconds'])
                self.assertEqual(state['migrations']['oren-move']['status'], 'arrived')
                self.assertIn('oren-home', state['settlements']['camp']['households'])
            if action['id'] == 'start-shelter':
                self.assertEqual(state['projects']['shelter']['status'], 'active')
                self.assertEqual(state['stocks']['founder-home']['timber'], 6)
            if action['id'] == 'pause-shelter':
                self.assertEqual(state['projects']['shelter']['status'], 'paused')
                self.assertEqual(state['stocks']['founder-home']['timber'], 6)
        # A prepared ordinary response survives process interruption but cannot
        # take effect without a separate explicit acceptance.
        pending = self.prepare(key, actor, phases[2][0])
        self.restart(key)
        pending_status = self.ok('/api/intent/status', pending)
        self.assertEqual(pending_status['status'], 'prepared')
        self.assertEqual(pending_status['intention'], phases[2][0]['words'])
        for action in phases[2]:
            _, result = self.act(key, actor, action, reject=action['id'] in expected['rejected_requests'])
            if action['id'] == 'finish-shelter':
                state = self.state(key)
                self.assertEqual(state['elapsed_time']['seconds'], expected['shelter_complete_seconds'])
                self.assertEqual(state['projects']['shelter']['status'], 'complete')
                self.assertEqual(state['assets']['shelter']['project'], 'shelter')
                self.assertEqual(state['material_flows']['project:shelter']['quantity'], 3)
        continuation = self.inputs['rise']['continuation']
        # Fixed actor instructions are unchanged. Only the evaluator's stopping
        # check reads cumulative synthetic Core time; it is never returned as a DTO.
        selected = self.state(key)
        model = selected['settlement_model']
        self.assertEqual(model['provision_interval_seconds'], expected['provision_interval'])
        elapsed = selected['elapsed_time']['seconds']
        self.assertEqual(elapsed, expected['shelter_complete_seconds'])
        self.assertEqual(continuation['until_elapsed_seconds'] % model['provision_interval_seconds'], 0)
        for index in range(continuation['maximum_requests']):
            if elapsed >= continuation['until_elapsed_seconds']:
                break
            before = self.state(key)
            next_at = before['provision']['next_at']
            _, result = self.act(key, actor, {'id': 'provision-wait-' + str(index),
                'action': continuation['action'], 'words': continuation['words']})
            after = self.state(key)
            elapsed = after['elapsed_time']['seconds']
            self.assertEqual(elapsed, min(before['elapsed_time']['seconds'] + 3600, next_at))
            if elapsed == next_at:
                self.assertEqual(after['provision']['next_at'], next_at + model['provision_interval_seconds'])
                for household, members in before['households'].items():
                    key_at = str(next_at) + ':' + household
                    assessment = after['provision']['assessments'][key_at]
                    demand = len(members['members']) * model['grain_per_person']
                    debit = before['stocks'][household]['grain'] - after['stocks'][household]['grain']
                    self.assertEqual(assessment['at'], next_at)
                    self.assertEqual(assessment['demand'], demand)
                    self.assertEqual(debit, assessment['delivered'])
                    self.assertGreaterEqual(debit, 0)
                    self.assertLessEqual(debit, max(0, before['stocks'][household]['grain'] - members['seed_reserve']))
                    self.assertEqual(assessment['deficit'] + debit, demand)
                    flow_id = 'provision:' + key_at
                    if debit:
                        flow = after['material_flows'][flow_id]
                        self.assertEqual(flow['kind'], 'consumption')
                        self.assertEqual(flow['quantity'], debit)
                        self.assertEqual(flow['elapsed_seconds'], next_at)
                    else:
                        self.assertNotIn(flow_id, after['material_flows'])
            else:
                self.assertEqual(after['provision']['next_at'], next_at)
                self.assertEqual(after['provision']['assessments'], before['provision']['assessments'])
                self.assertEqual(after['stocks'], before['stocks'])
        self.assertEqual(elapsed, continuation['until_elapsed_seconds'])
        state = self.state(key)
        self.assertEqual(state['elapsed_time']['seconds'], expected['final_seconds'])
        self.assertEqual(state['stocks']['founder-home']['timber'], expected['founder_timber'])
        self.assertEqual(state['stocks']['oren-home']['timber'], expected['oren_timber'])
        self.assertEqual(state['stocks']['founder-home']['grain'], expected['founder_grain'])
        self.assertEqual(state['stocks']['oren-home']['grain'], expected['oren_grain'])
        assessment = state['provision']['assessments'][str(expected['final_seconds']) + ':oren-home']
        self.assertEqual(assessment['deficit'], expected['oren_deficit'])
        self.assertEqual(state['campaign_time'], initial_calendar)
        self.assertIn(expected['refusal_text'], early['outcome']['summary'].lower())
        self.recover_all(key, actor)
        self.restore_fence(key, actor, self.inputs['rise']['restore_probe'])
        restored = self.state(key)
        self.assertEqual(restored['elapsed_time']['seconds'], state['elapsed_time']['seconds'])
        self.assertEqual(restored['campaign_time'], initial_calendar)
        self.evidence('rise', elapsed_seconds_before_restore=state['elapsed_time']['seconds'],
            post_restore_elapsed_seconds=restored['elapsed_time']['seconds'],
            founder_grain=expected['founder_grain'], oren_grain=expected['oren_grain'],
            observed_provision_deficit=assessment['deficit'], health_recovery_implemented=False,
            permission_attempt_rejected=True, duplicate_physical_project_rejected=True,
            authored_refusal_then_separate_agreement=True, civil_calendar_advanced=False)

    def test_quay_three_sessions_refusal_failed_route_custody_and_continuation(self):
        key, actor = self.create('quay')
        initial_calendar = copy.deepcopy(self.state(key)['campaign_time'])
        self.assertIsNone(initial_calendar['civil']['time'])
        initial_stock = copy.deepcopy(self.state(key)['stocks'])
        expected = self.oracle['quay']
        for phase_index, actions in enumerate(self.inputs['quay']['sessions']):
            if phase_index:
                self.restart(key)
                self.recover_all(key, actor)
            for action in actions:
                _, result = self.act(key, actor, action, discard_body=action['id'] == 'try-shortcut')
                status = 'completed_unsuccessfully' if action['id'] in expected['unsuccessful_requests'] else 'completed_successfully'
                self.assertEqual(result['status'], status)
                if action['action'] == 'request-dispatch-help':
                    self.assertIn(expected['refusal_text'], result['outcome']['summary'].lower())
                if action['id'] == 'ask-worker':
                    self.assertEqual(self.state(key)['stocks'], initial_stock)
        state = self.state(key)
        self.assertEqual(state['stocks'][actor]['sealed_dispatch'], expected['actor_dispatch'])
        self.assertEqual(state['stocks']['clerk-tray']['sealed_dispatch'], expected['tray_dispatch'])
        self.assertEqual(sum(row.get('sealed_dispatch', 0) for row in state['stocks'].values()), 1)
        self.assertEqual(state['actors'][actor]['current']['location']['value'], 'quay')
        self.assertEqual(state['elapsed_time']['seconds'], expected['final_seconds'])
        self.assertEqual(state['campaign_time'], initial_calendar)
        self.recover_all(key, actor)
        self.restore_fence(key, actor, self.inputs['quay']['restore_probe'])
        restored = self.state(key)
        probe_action = self.inputs['quay']['restore_probe']['action']
        probe_seconds = state['scene_rules']['actions'][probe_action]['duration_seconds']
        self.assertEqual(restored['elapsed_time']['seconds'], state['elapsed_time']['seconds'] + probe_seconds)
        self.assertEqual(restored['campaign_time'], initial_calendar)
        self.evidence('quay', elapsed_seconds_before_restore=state['elapsed_time']['seconds'],
            post_restore_elapsed_seconds=restored['elapsed_time']['seconds'],
            dispatch_actor=expected['actor_dispatch'], dispatch_tray=expected['tray_dispatch'],
            real_unsuccessful_attempts=expected['unsuccessful_requests'],
            authored_worker_refusal=True, post_delivery_return_to_quay=True,
            inferred_payment=False, civil_calendar_advanced=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine-source', required=True)
    parser.add_argument('--app-source', required=True)
    parser.add_argument('--catalog-commit', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--require-g10', action='store_true', help='Return 2 if the G10 criteria remain open.')
    args = parser.parse_args()
    output = Path(args.output).resolve()
    if output.is_relative_to(ROOT):
        parser.error('Write evidence outside the clean source checkout')
    os.environ['IRGS_SUSTAINED_ENGINE_SOURCE'] = args.engine_source
    os.environ['IRGS_SUSTAINED_APP_SOURCE'] = args.app_source
    os.environ['IRGS_SUSTAINED_CATALOG_SOURCE'] = str(ROOT)
    os.environ['IRGS_SUSTAINED_CATALOG_COMMIT'] = args.catalog_commit
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SustainedOrdinaryConsumers)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    oracle = json.loads((FIXTURE / 'evaluator_only/expectations.json').read_text(encoding='utf-8'))
    runtime_passed = (result.wasSuccessful() and result.testsRun == 2 and not result.skipped
                      and set(REPORTS) == {'rise', 'quay'})
    gate_status = 'held' if runtime_passed else 'blocked_by_runtime_failure'
    report = {'fixture_id': oracle['fixture_id'], 'source': SOURCE_SELECTION,
        'runtime_tests': {'run': result.testsRun, 'failures': len(result.failures),
                          'errors': len(result.errors), 'skipped': len(result.skipped),
                          'successful': runtime_passed,
                          'failure_details': [text for _, text in result.failures + result.errors]},
        'contexts': REPORTS, 'g10_original_acceptance': oracle['g10_acceptance'],
        'g10_plan_acceptance': oracle['g10_plan_acceptance'],
        'requirements_source': oracle['requirements_source'],
        'original_acceptance_journeys': oracle['acceptance_journeys'],
        'unselected_expansion_policy_required_by_this_consumer': False,
        'required_open_criteria': oracle['open_criteria'],
        'g10_qualified': False, 'live_provider_quality_verified': False,
        'semantic_quality_verified': False, 'gate_status': gate_status,
        'explanation': 'Original G10 sustained-depth qualification remains open; related G04/G06/G07 gaps retain their own gate IDs.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'report': str(output), 'runtime_tests_successful': runtime_passed,
                      'g10_gate': gate_status, 'required_open_criteria': [row['id'] for row in oracle['open_criteria']]}))
    if not runtime_passed:
        return 1
    return 2 if args.require_g10 else 0


if __name__ == '__main__':
    raise SystemExit(main())
