import json
from types import SimpleNamespace

import httpx
import pytest

from pipeline.llm import Agent, InvalidModelResponse
from pipeline.matching import match_laws
from pipeline.models import Generation
from pipeline.store import load_records, validate_store, write_json
from scripts.backfill_entry import pilot_leaves

GEN = Generation(model='offline-test', prompt_version='test', input_sha256='0' * 64)
ABSTENTION = dict(supported=False, score=None, confidence=0.1,
                  rationale='Kein belegbarer Effekt auf diese konkrete Zusage.',
                  law_passage_id=None, law_quote=None, criterion_quote=None, caveats=[])


class AbstainingAgent:
    def __init__(self):
        self.calls = 0

    def ask(self, task, data, schema, **kwargs):
        self.calls += 1
        return schema.model_validate(ABSTENTION), GEN

    def summary(self):
        return {'calls': self.calls}


def test_matching_batches_progress_without_changing_or_repaying_completed_laws(corpus):
    root, _, _, law = corpus
    second = law.model_copy(update={'id': 'bgbl-1-2025-101'})
    write_json(root / 'live/laws/bgbl-1-2025-101.json', second)
    agent = AbstainingAgent()
    first = match_laws(root=root, agent=agent, limit=1)
    assert first['processed_laws'] == [second.id] and first['deferred_laws'] == [law.id]
    assert not first['scope_complete'] and not first['selected_scope_only']
    before = (root / f'live/laws/{second.id}.json').read_bytes()
    next_batch = match_laws(root=root, agent=agent, limit=1)
    assert next_batch['processed_laws'] == [law.id] and next_batch['unchanged_laws'] == [second.id]
    assert next_batch['scope_complete'] and agent.calls == 2
    assert (root / f'live/laws/{second.id}.json').read_bytes() == before
    assert not match_laws(root=root, agent=agent, limit=1)['processed_laws']
    assert agent.calls == 2
    validate_store(root)


def test_explicit_matching_scope_never_marks_other_laws_checked(corpus):
    root, _, _, law = corpus
    second = law.model_copy(update={'id': 'bgbl-1-2025-101'})
    path = root / 'live/laws/bgbl-1-2025-101.json'
    write_json(path, second)
    before = path.read_bytes()
    result = match_laws(root=root, agent=AbstainingAgent(), law_ids=[law.id])
    assert result['processed_laws'] == [law.id] and result['selected_scope_only']
    assert path.read_bytes() == before
    validate_store(root)


def test_invalid_matching_scope_fails_before_model_or_data_changes(corpus):
    root, _, _, law = corpus
    agent = AbstainingAgent()
    for selection in ([], [law.id, law.id], ['unknown-law']):
        with pytest.raises(ValueError, match='unique existing'):
            match_laws(root=root, agent=agent, law_ids=selection)
    for limit in (0, -1, True, 2001):
        with pytest.raises(ValueError, match='limit'):
            match_laws(root=root, agent=agent, limit=limit)
    assert agent.calls == 0
    assert load_records(root, 'live', 'laws')[0].matching.status == 'pending'


def test_invalid_impact_quotes_never_enter_the_response_cache(corpus, tmp_path, monkeypatch):
    root, _, criterion, law = corpus
    monkeypatch.setenv('OPENROUTER_API_KEY', 'unit-test-only')
    proposal = dict(supported=True, score=2, confidence=0.8, rationale='Ein synthetischer Testvorschlag.',
                    law_passage_id=law.passages[0].id, law_quote='Dieses Zitat steht nicht im Gesetz.',
                    criterion_quote=criterion.reference.quote, caveats=[])
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={
        'usage': {'cost': 0.001}, 'choices': [{'finish_reason': 'stop',
        'message': {'content': json.dumps(proposal)}}]})))
    agent = Agent(cache=tmp_path / 'llm', client=client)
    with pytest.raises(InvalidModelResponse, match='verbatim'):
        match_laws(root=root, agent=agent, law_ids=[law.id])
    assert agent.calls == 3 and not list((tmp_path / 'llm').glob('*.json'))
    assert not load_records(root, 'live', 'impacts')
    assert load_records(root, 'live', 'laws')[0].matching.status == 'pending'


def test_source_term_pilot_is_deterministic_bounded_and_not_a_political_effect_filter():
    program = SimpleNamespace(leaves=[SimpleNamespace(id=f'leaf-{i}', text=term + ' Quellentext.' * 10)
        for i, term in enumerate(['Wohnen', 'Familiennachzug', 'Wohnen', 'Familiennachzug', 'Wohnen'])])
    assert pilot_leaves(program, ['Familiennachzug', 'Wohnen']) == ['leaf-0', 'leaf-1', 'leaf-2', 'leaf-3']
    for terms in ([], ['x'], ['not in document']):
        with pytest.raises(ValueError):
            pilot_leaves(program, terms)
