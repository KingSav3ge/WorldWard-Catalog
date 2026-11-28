"""Check Catalog source identity and campaign records without Engine or App."""
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re

ROOT = Path(__file__).resolve().parent
CAMPAIGN_TYPES = {'SS': 'short_story', 'CC': 'curated', 'FC': 'full',
    'MC': 'major', 'GC': 'grand', 'CSS': 'simulation_system'}
DEVELOPMENT_STATUSES = ('concept_draft', 'planned', 'in_development')


def source_files(root):
    return {p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()
        and p != root / 'release.json' and '__pycache__' not in p.parts
        and p.suffix not in ('.pyc', '.log', '.tmp', '.bak')}


def safe_path(root, name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or path.as_posix() != name
            or '..' in path.parts or '\\' in name or ':' in name):
        raise RuntimeError('Invalid Catalog source path')
    result = root.joinpath(*path.parts)
    if any(p.is_symlink() for p in (result, *result.parents) if p.is_relative_to(root)):
        raise RuntimeError('Linked Catalog source path')
    if not result.resolve().is_relative_to(root.resolve()):
        raise RuntimeError('Catalog source escapes its directory')
    return result


def verify_campaign_records(portfolio, listings):
    """Validate editorial input; no runtime availability is inferred here."""
    if (not isinstance(portfolio, dict) or type(portfolio.get('schema_version')) is not int
            or portfolio['schema_version'] != 1
            or not isinstance(portfolio.get('entries'), list) or not portfolio['entries']
            or not isinstance(listings, dict) or type(listings.get('schema_version')) is not int
            or listings['schema_version'] != 1):
        raise RuntimeError('Unsupported campaign catalogue schema')
    seen, statuses = set(), Counter()
    for record in portfolio['entries']:
        if not isinstance(record, dict):
            raise RuntimeError('Campaign concept must be an object')
        identity = record.get('catalogue_id')
        match = re.fullmatch(r'(SS|CC|FC|MC|GC|CSS)-(P)?[0-9]{2}', identity) if isinstance(identity, str) else None
        if not match:
            raise RuntimeError('Invalid campaign catalogue ID')
        if identity in seen:
            raise RuntimeError('Duplicate campaign catalogue ID: ' + identity)
        seen.add(identity)
        expected_slate = 'system' if match[1] == 'CSS' else 'future' if match[2] else 'launch'
        if record.get('campaign_type') != CAMPAIGN_TYPES[match[1]] or record.get('slate') != expected_slate:
            raise RuntimeError('Campaign type or slate differs from its ID: ' + identity)
        status = record.get('development_status')
        if status not in DEVELOPMENT_STATUSES:
            raise RuntimeError('Unknown campaign development status: ' + identity)
        statuses[status] += 1
        availability = record.get('availability')
        readiness = record.get('readiness')
        review = record.get('design_review')
        if (not isinstance(availability, dict) or type(availability.get('preview')) is not bool
                or availability.get('release_approved') is not False
                or availability.get('entitlement_active') is not False
                or not isinstance(readiness, dict) or readiness.get('full_campaign_ready') is not False
                or not isinstance(review, dict) or review.get('runtime_certified') is not False):
            raise RuntimeError('Campaign preview requires explicit unreleased, unentitled and uncertified flags: ' + identity)
        if any(key in record for key in ('available_slice', 'current_campaign_id', 'launch_capability', 'playable')):
            raise RuntimeError('Runtime availability belongs to App/Engine, not preview input: ' + identity)
    visible = listings.get('visible_campaign_ids')
    if (not isinstance(visible, list) or not visible
            or any(not isinstance(identity, str) or not identity.strip() for identity in visible)
            or len(visible) != len(set(visible))):
        raise RuntimeError('Campaign discovery IDs must be nonempty and unique')
    if listings.get('registration_alone_grants_listing') is not False:
        raise RuntimeError('Technical registration cannot grant campaign discovery')
    references = listings.get('starting_scenario_references')
    if not isinstance(references, list):
        raise RuntimeError('Starting-scenario references must be a list')
    seen_references = set()
    for reference in references:
        if not isinstance(reference, dict):
            raise RuntimeError('Starting-scenario reference must be an object')
        identity = reference.get('id')
        if (not isinstance(identity, str) or not identity.strip() or identity in seen_references
                or reference.get('campaign_id') not in visible or reference.get('can_launch') is not False):
            raise RuntimeError('Starting-scenario references must be unique, listed and unable to grant launch')
        seen_references.add(identity)
    return {'status': 'verified', 'unique_concepts': len(seen),
        'development_status_counts': {status: statuses[status] for status in DEVELOPMENT_STATUSES},
        'runtime_availability_inferred': False}


def verify_catalog(root=ROOT):
    release = json.loads((root / 'release.json').read_text(encoding='utf-8'))
    if release.get('component') != 'IRGS-Catalog' or release.get('schema_version') != 1:
        raise RuntimeError('No selected IRGS Catalog binding')
    hashes = release['files_sha256']
    if not hashes or set(hashes) != source_files(root):
        raise RuntimeError('Catalog inventory differs from its release binding')
    for name, expected in hashes.items():
        if hashlib.sha256(safe_path(root, name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Catalog hash mismatch: ' + name)
    portfolio = json.loads((root / 'data/campaign_portfolio.json').read_text(encoding='utf-8'))
    listings = json.loads((root / 'data/campaign_listings.json').read_text(encoding='utf-8'))
    campaign_records = verify_campaign_records(portfolio, listings)
    source = portfolio['source']
    prefix = 'IRGS_Catalog/'
    if not source['path'].startswith(prefix):
        raise RuntimeError('Catalogue provenance must identify its owned design source')
    original = safe_path(root, source['path'][len(prefix):])
    if hashlib.sha256(original.read_bytes()).hexdigest() != source['sha256']:
        raise RuntimeError('Catalogue design source hash differs')
    spec = importlib.util.spec_from_file_location('catalog_historical_source_check',
        root / 'historical_details_package.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    historical = checker.package_status(root / 'historical_details/manifest.json')
    spec = importlib.util.spec_from_file_location('catalog_solo_fixture_check',
        root / 'solo_evaluation.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    solo = checker.validate_fixture(root / 'evaluation/solo_r00_v1')
    spec = importlib.util.spec_from_file_location('catalog_proposal_compatibility_check',
        root / 'solo_proposal_compatibility.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    proposals = checker.validate_compatibility(root)
    spec = importlib.util.spec_from_file_location('catalog_scripted_response_check',
        root / 'scripted_responses.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    responses = checker.validate_library(checker.load_library(root / 'responses/depot_v1/library.json'))
    expanded_responses = checker.validate_library(checker.load_library(root / 'responses/depot_v2/library.json'))
    original_responses = checker.validate_library(checker.load_library(root / 'responses/routine_v1/library.json'))
    spec = importlib.util.spec_from_file_location('catalog_shared_response_check',
        root / 'response_depot_compatibility.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    shared_responses = checker.validate_fixture(root)
    spec = importlib.util.spec_from_file_location('catalog_integrated_response_check',
        root / 'integrated_response_compatibility.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    integrated_responses = checker.validate_compatibility(root)
    spec = importlib.util.spec_from_file_location('catalog_development_interop_check',
        root / 'development_interop_compatibility.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    development_interop = checker.validate_compatibility(root)
    spec = importlib.util.spec_from_file_location('catalog_phase_response_check',
        root / 'phase_response_compatibility.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    phase_responses = checker.validate_compatibility(root)
    spec = importlib.util.spec_from_file_location('catalog_player_start_check',
        root / 'player_start_evaluation.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    player_starts = checker.validate_fixture(root)
    spec = importlib.util.spec_from_file_location('catalog_start_context_check',
        root / 'start_context_evaluation.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    start_context = checker.validate_fixture(root)
    spec = importlib.util.spec_from_file_location('catalog_alpha_context_check', root / 'alpha_context_evaluation.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    alpha_contexts = checker.validate_fixture(root)
    spec = importlib.util.spec_from_file_location('catalog_alpha_journey_check', root / 'alpha_journey_evaluation.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    alpha_journeys = checker.validate_fixture(root)
    spec = importlib.util.spec_from_file_location('catalog_grounding_quality_check', root / 'grounding_quality.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    grounding_quality = checker.validate_fixture(root)
    spec = importlib.util.spec_from_file_location('catalog_world_examples_check', root / 'world_authoring_examples.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    world_examples = checker.validate_fixture(root)
    spec = importlib.util.spec_from_file_location('catalog_intent_world_draft_check', root / 'intent_world_draft_evaluation.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    intent_world_draft = checker.validate_fixture(root)
    spec = importlib.util.spec_from_file_location('catalog_adopted_consequences_check', root / 'adopted_consequences_evaluation.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    adopted_consequences = checker.validate_fixture(root)
    return {'status': 'verified', 'component': 'IRGS-Catalog', 'files': len(hashes),
        'concepts': len(portfolio['entries']), 'campaign_release_approved_by_check': False,
        'campaign_records': campaign_records, 'historical_details': historical,
        'solo_evaluation': solo, 'solo_proposal_compatibility': proposals,
        'scripted_responses': responses, 'expanded_scripted_responses': expanded_responses,
        'original_scripted_responses': original_responses,
        'shared_response_compatibility': shared_responses,
        'integrated_response_compatibility': integrated_responses,
        'development_interoperability': development_interop,
        'phase_response_compatibility': phase_responses,
        'player_start_evaluation': player_starts,
        'start_context_evaluation': start_context, 'alpha_context_evaluation': alpha_contexts,
        'alpha_journey_evaluation': alpha_journeys,
        'grounding_quality': grounding_quality, 'world_authoring_examples': world_examples,
        'intent_world_draft_evaluation': intent_world_draft,
        'adopted_consequences_evaluation': adopted_consequences}


if __name__ == '__main__':
    print(json.dumps(verify_catalog()))
