from types import SimpleNamespace

import pytest

from pipeline.catalog import load_catalog
from pipeline.documents import pages_to_markdown
from pipeline.llm import InvalidModelResponse
from pipeline.models import Generation
from pipeline.programs import structure_paragraphs
from pipeline.store import ROOT
from scripts.check_checkpoint import check


def test_other_programmes_have_inspected_dates_without_invented_licences():
    catalog = load_catalog(ROOT / 'data')
    for source in catalog.programs:
        assert source.published and source.published <= catalog.period_start
        if source.id != 'gruene-2025':
            assert source.rights.license_url is None
            assert source.rights.status == 'permission-required'


def test_tiny_invalid_outline_uses_bounded_review_without_rewriting():
    markdown, raw = pages_to_markdown(['A source paragraph that must stay verbatim.'], 'test-program')
    class Agent:
        calls = []
        def ask(self, task, data, schema, **kwargs):
            self.calls.append(kwargs['review'])
            if not kwargs['review']:
                raise InvalidModelResponse('Bad primary structure')
            result = schema.model_validate({'groups': [{'start': 0, 'end': 0, 'sections': ['Chapter']}]})
            kwargs['validator'](result)
            return result, Generation(model='test/reviewer', prompt_version='v1', input_sha256='a' * 64)
    agent = Agent()
    leaves, tree, _ = structure_paragraphs(raw, markdown, 'Test', 'test-program', agent)
    assert agent.calls == [False, True]
    assert leaves == raw and tree.children[0].leaf_ids == [raw[0].id]


def test_programme_runner_keeps_actual_terms_and_checkpoints(monkeypatch, tmp_path):
    from scripts import programmes_batch as module
    source = next(p for p in load_catalog(ROOT / 'data').programs if p.id == 'ssw-2025')
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(module, 'load_catalog', lambda root: SimpleNamespace(
        programs=[source], election_year=2025, period_start=source.published))
    monkeypatch.setattr(module, 'validate_store', lambda root: {'valid': True})
    records = []
    monkeypatch.setattr(module, 'load_records', lambda *args: records)
    def ingest(**kwargs):
        assert kwargs['expected_sha256'] == source.sha256
        assert kwargs['license_note'].startswith(source.rights.note)
        assert kwargs['published'] == source.published
        records.append(SimpleNamespace(id=source.id, leaves=[1], criteria_extraction=[]))
        return {'program_id': source.id, 'paragraphs': 1}
    def extract(**kwargs):
        assert kwargs['checkpoint'] and kwargs['strong_fallback']
        assert kwargs['program_id'] == source.id and kwargs['workers'] == 4
        return {'new_criteria': 0}
    monkeypatch.setattr(module, 'ingest_program', ingest)
    monkeypatch.setattr(module, 'extract_criteria', extract)
    result = module.run(source.id, {'source_mode': 'attributed-transcription'}, root=tmp_path,
                        agent=SimpleNamespace(summary=lambda: {'reported_cost_usd': 0}))
    assert result['status'] == 'completed'
    assert (tmp_path / '.cache/programmes/ssw-2025/result.json').exists()


@pytest.mark.parametrize('case,expected', [
    ('active', 'may be spending'), ('artifact', 'newer source ledger'),
    ('lost', 'without a retained ledger'), ('other', None), ('skipped', None),
])
def test_checkpoint_guard_is_source_specific(case, expected):
    job = {'name': 'import (ssw-2025)', 'status': 'completed', 'steps': []}
    artifacts = []
    if case == 'active':
        job['status'] = 'in_progress'
    if case == 'artifact':
        artifacts = [{'name': 'programme-checkpoint-ssw-2025'}]
    if case in ('lost', 'skipped'):
        job['steps'] = [{'name': 'Import source and extract every leaf', 'started_at': 'now',
                         'conclusion': 'skipped' if case == 'skipped' else 'failure'}]
    if case == 'other':
        job['name'] = 'import (spd-2025)'
        job['status'] = 'in_progress'
        artifacts = [{'name': 'programme-checkpoint-spd-2025'}]
    def api(path):
        return {'jobs': [job]} if path.endswith('/jobs') else {'artifacts': artifacts}
    kwargs = dict(current=3, resume=1, target='ssw-2025')
    history = {'total_count': 1, 'workflow_runs': [{'id': 2}]}
    if expected:
        with pytest.raises(RuntimeError, match=expected):
            check(history, api, **kwargs)
    else:
        check(history, api, **kwargs)


def test_exact_resume_does_not_reject_its_own_ledger():
    check({'total_count': 1, 'workflow_runs': [{'id': 2}]}, lambda _: pytest.fail('unexpected API'),
          current=3, resume=2, target='ssw-2025')
