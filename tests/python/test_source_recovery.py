import pytest

from pipeline.programs import CriteriaResponse, StructuredParagraphs
from pipeline.store import write_json
from scripts.recover_tree import CachedOutlineAgent


def test_recovery_uses_cached_structure_and_labels_missing_source_blocks(tmp_path, monkeypatch):
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    agent = CachedOutlineAgent(cache=tmp_path)
    def forbidden(*args, **kwargs):
        raise AssertionError('Recovery must not contact the model provider')
    monkeypatch.setattr(agent.client, 'post', forbidden)
    data = {'blocks': [{'index': 0, 'page': 8, 'text': 'Original source paragraph'}]}
    *_, path = agent._request_context('structure', data, StructuredParagraphs)
    write_json(path, {'groups': [{'start': 0, 'end': 0, 'sections': ['Original chapter']} ]})
    result, generation = agent.ask('structure', data, StructuredParagraphs)
    assert result.groups[0].sections == ['Original chapter']
    assert generation.model == agent.model and agent.cached_blocks == 1
    missing = {'blocks': [{'index': 0, 'page': 9, 'text': 'Original unfinished paragraph'}]}
    result, generation = agent.ask('structure', missing, StructuredParagraphs)
    assert result.groups[0].sections == ['Strukturierung noch offen', 'PDF-Seite 9']
    assert generation.model == 'politrace/source-block-recovery'
    assert agent.fallback_blocks == 1 and agent.calls == 0
    assert len(list(tmp_path.glob('*.json'))) == 1  # Never cache deterministic text as model output.


def test_recovery_rechecks_cache_and_cannot_create_claims(tmp_path):
    agent = CachedOutlineAgent(cache=tmp_path)
    data = {'blocks': [{'index': 0, 'page': 8, 'text': 'Original source paragraph'}]}
    *_, path = agent._request_context('structure', data, StructuredParagraphs)
    write_json(path, {'groups': [{'start': 5, 'end': 5, 'sections': ['Wrong cached range']}]})
    def check(result):
        if result.groups[0].start != 0:
            raise ValueError('Source block omitted')
    result, generation = agent.ask('structure', data, StructuredParagraphs, validator=check)
    assert result.groups[0].start == 0 and generation.model == 'politrace/source-block-recovery'
    with pytest.raises(ValueError, match='outline structure only'):
        agent.ask('invent criteria', data, CriteriaResponse)
    assert agent.calls == 0
