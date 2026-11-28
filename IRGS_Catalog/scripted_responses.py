"""Catalog text validation and deterministic formatting over host-scoped facts.

This module imports no Engine, App or provider. It cannot authenticate a context
or establish its truth: the trusted host must supply an actor-filtered projection.
Returned text is plain text; the App must escape it for its display surface.
"""
import json
from pathlib import Path
import re
from string import Formatter

DEFAULT_LIBRARY = Path(__file__).resolve().parent / 'responses/depot_v1/library.json'
SOURCES = {'host_status', 'actor_view', 'received_record', 'committed_receipt', 'player_request'}
ROLES = {'lead': 0, 'body': 1, 'detail': 2, 'prompt': 3}
TYPES = {'label', 'integer', 'source_text'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def keys(value, expected):
    require(isinstance(value, dict) and set(value) == set(expected.split()), 'Unknown or missing response fields')


def text(value, limit, *, multiline=False):
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= limit
            and all(ord(c) >= 32 or multiline and c in '\n\t' for c in value), 'Invalid response text')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'Duplicate response JSON field')
        result[key] = value
    return result


def load_library(path=DEFAULT_LIBRARY):
    path = Path(path)
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'Linked response library')
    require(path.stat().st_size <= 1048576, 'Response library exceeds size limit')
    library = json.loads(path.read_bytes(), object_pairs_hook=_pairs)
    validate_library(library)
    return library


def validate_library(library):
    keys(library, 'schema_version library_id version language source_ref rights authority families recipes')
    library_id = library['library_id']
    require(isinstance(library_id, str), 'Unsupported response library identity')
    identities = {
        'irgs-routine-responses-v1': (1, '1.0.0', 'authored:irgs-catalog:routine-responses:v1'),
        'irgs-response-depot-v1': (2, '1.0.0', 'authored:irgs-catalog:response-depot:v1'),
        'irgs-response-depot-v2': (2, '2.0.0', 'authored:irgs-catalog:response-depot:v2'),
    }
    depot = library_id in ('irgs-response-depot-v1', 'irgs-response-depot-v2')
    require(type(library['schema_version']) is int and library_id in identities
            and (library['schema_version'], library['version'], library['source_ref']) == identities[library_id]
            and library['language'] == 'en', 'Unsupported response library identity')
    require(library['rights'] == {'authorship': 'original-authored-presentation-text',
        'permitted_use': ['local-presentation', 'synthetic-evaluation'],
        'imported_material': 'none', 'external_processing': 'host-policy-required'},
        'Explicit response provenance and processing scope required')
    require(library['authority'] == {'presentation_only': True, 'campaign_effects': False,
        'player_drafts_require_explicit_submission': True, 'provider_dispatch': False},
        'Response content cannot establish effects, player decisions or dispatch')
    require(all(type(value) is bool for value in library['authority'].values()), 'Authority flags must be boolean')
    families, seen, count = library['families'], {}, 0
    require(isinstance(families, list) and len(families) >= 75, 'Large authored response library required')
    for family in families:
        keys(family, 'id domain channel source_kind state role slots variants' + (' intent_tag' if depot else ''))
        identity = family['id']
        require(isinstance(identity, str) and re.fullmatch(r'[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+', identity)
                and identity not in seen, 'Invalid or duplicate response family ID')
        require(isinstance(family['domain'], str) and family['domain'] in {'request', 'recovery', 'knowledge', 'inventory', 'work',
                'settlement', 'place', 'time', 'navigation', 'player'}, 'Unknown response domain')
        require(isinstance(family['source_kind'], str) and family['source_kind'] in SOURCES
                and family['channel'] in ('system', 'player_draft')
                and isinstance(family['role'], str) and family['role'] in ROLES,
                'Invalid response audience/source/role')
        require(isinstance(family['state'], str) and re.fullmatch(r'[a-z][a-z0-9_]*', family['state']),
                'Explicit response state required')
        require((family['channel'] == 'player_draft') == (family['source_kind'] == 'player_request'),
                'Player drafts must remain separate from system facts')
        if depot:
            if family['channel'] == 'player_draft':
                require(family['state'] == 'draft' and isinstance(family['intent_tag'], str)
                        and re.fullmatch(r'[a-z][a-z0-9_]*', family['intent_tag']),
                        'Depot drafts require a semantic intent tag, not an operation binding')
            else:
                require(family['intent_tag'] is None, 'System responses cannot select a player intention')
        require(isinstance(family['slots'], dict) and all(isinstance(k, str)
                and re.fullmatch(r'[a-z][a-z0-9_]*', k) and v in TYPES
                for k, v in family['slots'].items()), 'Invalid response slots')
        variants = family['variants']
        require(isinstance(variants, list) and 1 <= len(variants) <= 8
                and all(isinstance(v, str) for v in variants)
                and len(set(variants)) == len(variants), 'Unique authored variants required')
        for variant in variants:
            text(variant, 1000)
            fields = []
            for _, field, spec, conversion in Formatter().parse(variant):
                if field is not None:
                    require(field in family['slots'] and not spec and conversion is None,
                            'Only declared scalar response placeholders are allowed')
                    fields.append(field)
            require(set(fields) == set(family['slots']), 'Variant omits declared fact slots')
        seen[identity] = family
        count += len(variants)
    anchor = seen.get('receipt.exact')
    require(anchor is not None and anchor['variants'] == ['{receipt_text}']
            and anchor['slots'] == {'receipt_text': 'source_text'}
            and anchor['role'] == 'body' and anchor['source_kind'] == 'committed_receipt'
            and anchor['state'] == 'committed' and anchor['channel'] == 'system',
            'Committed outcome requires an exact receipt anchor')
    require(count >= 300, 'At least 300 authored response variants required')
    require(isinstance(library['recipes'], list) and library['recipes'], 'Composition recipes required')
    recipes = set()
    for recipe in library['recipes']:
        keys(recipe, 'id families required')
        require(isinstance(recipe['id'], str) and recipe['id'] not in recipes, 'Duplicate recipe ID')
        require(isinstance(recipe['families'], list) and 1 <= len(recipe['families']) <= 8
                and all(isinstance(f, str) and f in seen for f in recipe['families'])
                and len(set(recipe['families'])) == len(recipe['families']), 'Invalid recipe families')
        require(isinstance(recipe['required'], list) and recipe['required']
                and all(isinstance(f, str) and f in recipe['families'] for f in recipe['required'])
                and len(set(recipe['required'])) == len(recipe['required']), 'Required recipe facts missing')
        ranks = [ROLES[seen[f]['role']] for f in recipe['families']]
        require(ranks == sorted(ranks), 'Recipe clauses out of order')
        if any(seen[f]['source_kind'] == 'committed_receipt' for f in recipe['families']):
            require('receipt.exact' in recipe['required'], 'Result recipe cannot omit exact receipt')
        recipes.add(recipe['id'])
    return {'status': 'verified', 'library_id': library['library_id'], 'version': library['version'], 'families': len(families),
            'variants': count, 'recipes': len(recipes), 'provider_dispatch': False,
            'runtime_integration_verified_by_schema': False}


def _family(library, family_id):
    result = next((f for f in library['families'] if f['id'] == family_id), None)
    require(result is not None, 'Unknown response family; host must retain its unresolved result')
    return result


def render_fragment(library, family_id, context, *, variant=0):
    """Format an already validated library against one trusted, scoped fact packet."""
    family = _family(library, family_id)
    keys(context, 'actor_id snapshot_id source_ref source_kind state values')
    for key in ('actor_id', 'snapshot_id', 'source_ref'):
        text(context[key], 256)
    require(context['source_kind'] == family['source_kind'] and context['state'] == family['state'],
            'Response source or state mismatch')
    require(isinstance(context['values'], dict) and set(context['values']) == set(family['slots']),
            'Missing or extra response facts')
    for key, kind in family['slots'].items():
        value = context['values'][key]
        if kind == 'integer':
            require(type(value) is int and 0 <= value <= 10**12, 'Invalid response quantity')
        else:
            text(value, 4000 if kind == 'source_text' else 160, multiline=kind == 'source_text')
    values = context['values']
    if 'worked_seconds' in values and 'required_seconds' in values:
        require(values['worked_seconds'] <= values['required_seconds'], 'Work display exceeds its recorded requirement')
    require(type(variant) is int and 0 <= variant < len(family['variants']), 'Unknown response variant')
    return family['variants'][variant].format_map(context['values'])


def compose(library, parts):
    """Join whole clauses from one actor/snapshot; never trim or rewrite receipt text."""
    require(isinstance(parts, list) and 1 <= len(parts) <= 8, 'Bounded response parts required')
    result, scopes, channels, ranks, records, identities = [], set(), set(), [], {}, set()
    for part in parts:
        keys(part, 'family_id variant context')
        family = _family(library, part['family_id'])
        context = part['context']
        rendered = render_fragment(library, family['id'], context, variant=part['variant'])
        scopes.add((context['actor_id'], context['snapshot_id']))
        channels.add(family['channel'])
        ranks.append(ROLES[family['role']])
        record = (context['source_kind'], context['source_ref'])
        prior_state, prior_values = records.get(record, (context['state'], {}))
        require(prior_state == context['state'], 'Conflicting response states')
        require(all(prior_values[key] == value for key, value in context['values'].items()
                    if key in prior_values), 'Conflicting response facts')
        records[record] = (context['state'], {**prior_values, **context['values']})
        identity = (family['id'], context['source_ref'])
        require(identity not in identities, 'Duplicate response fact')
        identities.add(identity)
        result.append(rendered)
    require(len(scopes) == 1, 'Cannot mix actors or snapshots')
    require(len(channels) == 1, 'Cannot mix player intentions with system responses')
    require('player_draft' not in channels or len(parts) == 1, 'Player drafts cannot be combined into decisions')
    require(ranks == sorted(ranks) and ranks.count(0) <= 1 and ranks.count(3) <= 1,
            'Incompatible clause ordering')
    if any(p['context']['source_kind'] == 'committed_receipt' for p in parts):
        require(any(p['family_id'] == 'receipt.exact' for p in parts), 'Committed response needs exact receipt')
    return ' '.join(result)


def compose_recipe(library, recipe_id, contexts, *, variants=None):
    recipe = next((r for r in library['recipes'] if r['id'] == recipe_id), None)
    require(recipe is not None, 'Unknown response recipe')
    require(isinstance(contexts, dict) and set(recipe['required']) <= set(contexts)
            and set(contexts) <= set(recipe['families']), 'Recipe lacks required facts or has extra facts')
    variants = {} if variants is None else variants
    require(isinstance(variants, dict) and set(variants) <= set(contexts), 'Unknown recipe variant selection')
    return compose(library, [{'family_id': family, 'variant': variants.get(family, 0),
                             'context': contexts[family]}
                            for family in recipe['families'] if family in contexts])


if __name__ == '__main__':
    print(json.dumps(validate_library(load_library())))
