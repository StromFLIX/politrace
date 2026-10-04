
import pytest

from pipeline.experiment import (
    DedupDecision,
    Equivalences,
    Equivalent,
    Index,
    Judgments,
    PairJudgment,
    PairVerification,
    Verifications,
    analyse,
    complete_link_groups,
    deduplicate,
    exact_ids,
    retrieve_all,
)
from pipeline.models import Generation, LeafExtraction
from pipeline.store import load_records, validate_store, write_json

GEN = Generation(model='test/model', prompt_version='test-v1', input_sha256='a' * 64)


def decision(left, right):
    return DedupDecision(left_id=left, right_id=right,
        decision=Equivalent(pair_id=f'{left}-{right}', equivalent=True, rationale='Same exact commitment.',
                            left_quote='Source quotation.', right_quote='Source quotation.'), generation=GEN)


def test_complete_link_never_collapses_transitive_similarity():
    groups = complete_link_groups(['aa', 'bb', 'cc'], [decision('aa', 'bb'), decision('bb', 'cc')])
    assert [g.member_ids for g in groups] == [['aa', 'bb'], ['cc']]
    groups = complete_link_groups(['aa', 'bb', 'cc'], [decision('aa', 'bb'), decision('bb', 'cc'),
                                                     decision('aa', 'cc')])
    assert len(groups) == 1


def test_index_uses_german_stemming_and_deterministic_order():
    index = Index({'aa': 'Mindestlohn erhöhen und Löhne', 'bb': 'Strom Energie', 'cc': 'Löhne'})
    assert index.rank('Lohn Mindestlohn')[0] == 'aa'
    assert index.rank('Energie') == ['bb']
    assert index.rank('unbekannt') == []


def test_response_ids_cannot_be_missing_duplicated_or_invented():
    a = Equivalent(pair_id='aa', equivalent=False, rationale='Not equivalent, different scope.',
                   left_quote=None, right_quote=None)
    for ids in [['aa', 'bb'], ['bb']]:
        with pytest.raises(ValueError):
            exact_ids([a], ids, 'pair_id')
    with pytest.raises(ValueError):
        exact_ids([a, a], ['aa', 'bb'], 'pair_id')


def test_different_targets_never_even_reach_merge_agent(corpus):
    _, _, criterion, _ = corpus
    other = criterion.model_copy(deep=True, update={'id': 'spd-2025-ac-other',
        'test': criterion.test.replace('15', '16')})
    class NoCalls:
        def ask(self, *args, **kwargs):
            raise AssertionError('Different amounts cannot be merged')
    groups, pairs = deduplicate([criterion, other], NoCalls())
    assert len(groups) == 2 and pairs == []


def test_reverse_and_provision_retrieval_stay_inside_programme_window(corpus):
    _, program, criterion, law = corpus
    prior = law.model_copy(update={'id': 'old-law', 'published_at': program.published_at.replace(year=2024)})
    selected, eligible = retrieve_all([law, prior], [criterion], [program])
    assert selected[law.id] == [criterion.id]
    assert selected[prior.id] == [] and eligible[prior.id] == set()


class OfflineAgent:
    model = 'test/model'
    review_model = 'test/reviewer'
    reported_cost_usd = 0.0
    reserved_usd = 0.0

    def __init__(self, root, supported=True):
        self.cache = root / 'cache/llm'
        self.supported = supported
        self.calls = 0

    def summary(self):
        return {'reported_cost_usd': 0, 'calls': self.calls}

    def ask(self, task, data, schema, **options):
        self.calls += 1
        if schema is Equivalences:
            result = Equivalences(pairs=[])
        elif schema is Judgments:
            pairs = []
            for criterion in data['criteria']:
                pairs.append(PairJudgment(criterion_id=criterion['id'], supported=self.supported,
                    disposition='proposed_link' if self.supported else 'missing_context',
                    score=2 if self.supported else None, confidence=0.8,
                    rationale='Direct source-backed increase.' if self.supported else 'Missing historical base law.',
                    law_passage_id=data['passages'][0]['id'] if self.supported else None,
                    law_quote=data['passages'][0]['text'] if self.supported else None,
                    criterion_quote=criterion['quote'] if self.supported else None, caveats=[]))
            result = Judgments(pairs=pairs)
        elif schema is Verifications:
            result = Verifications(pairs=[PairVerification(criterion_id=p['criterion_id'], accepted=False,
                rationale='Disputed magnitude of impact.', caveats=[]) for p in data['proposals']])
        else:
            raise AssertionError(schema)
        options['validator'](result)
        return result, GEN


def finish_source(root, program, criterion):
    for leaf in program.leaves:
        program.criteria_extraction.append(LeafExtraction(leaf_id=leaf.id,
            criterion_ids=[criterion.id] if leaf.id == criterion.leaf_id else [],
            abstention_reason=None if leaf.id == criterion.leaf_id else 'Rhetoric, not a commitment.', generation=GEN))
    write_json(root / 'live/programs' / f'{program.id}.json', program)


@pytest.mark.parametrize('supported', [True, False])
def test_end_to_end_dispositions_citations_disagreements_and_free_resume(corpus, supported):
    root, program, criterion, law = corpus
    finish_source(root, program, criterion)
    agent = OfflineAgent(root, supported=supported)
    result = analyse(root=root, agent=agent, program_id=program.id)
    assert result['laws'] == result['expected_laws'] == 1 and result['candidate_pairs'] == 1
    impacts = load_records(root, 'live', 'impacts')
    assert len(impacts) == int(supported)
    if supported:
        assert impacts[0].verification == 'needs_review' and impacts[0].review.status == 'proposed'
    validate_store(root)
    before = agent.calls
    analyse(root=root, agent=agent, program_id=program.id)
    assert agent.calls == before
    assert (root / result['report']).exists()


def test_incomplete_source_is_not_a_full_programme_experiment(corpus):
    root, program, _, _ = corpus
    with pytest.raises(ValueError, match='fully processed'):
        analyse(root=root, agent=OfflineAgent(root), program_id=program.id)


def test_strong_fallback_uses_same_citation_checks_and_never_overwrites(corpus):
    from pipeline.llm import InvalidModelResponse
    from pipeline.programs import CriteriaBatch, LeafCriteria, extract_criteria

    root, program, _, _ = corpus
    for path in (root / 'live/criteria').glob('*.json'):
        path.unlink()
    class Agent:
        reviews = []
        def ask(self, task, data, schema, **options):
            self.reviews.append(options.get('review', False))
            if not options.get('review'):
                raise InvalidModelResponse('Cannot reproduce the source quotation')
            assert len(data['paragraphs']) == 1
            result = CriteriaBatch(paragraphs=[LeafCriteria(leaf_id=data['paragraphs'][0]['leaf_id'],
                criteria=[], abstention_reason='No testable commitment in this fixture.')])
            options['validator'](result)
            return result, GEN
    agent = Agent()
    extract_criteria(root=root, program_id=program.id, agent=agent, batch_size=4,
                     strong_fallback=True, checkpoint=True)
    assert agent.reviews.count(True) == 2
    assert len(load_records(root, 'live', 'programs')[0].criteria_extraction) == 2
    validate_store(root)


def test_criteria_checkpoint_survives_a_later_failed_leaf(corpus):
    from pipeline.programs import CriteriaResponse, extract_criteria

    root, program, _, _ = corpus
    # Remove the fixture criterion to make both source leaves pending.
    for p in (root / 'live/criteria').glob('*.json'):
        p.unlink()
    class Agent:
        calls = 0
        def ask(self, *args, **kwargs):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError('Simulated provider outage')
            return CriteriaResponse(criteria=[], abstention_reason='Fixture abstention.'), GEN
    with pytest.raises(RuntimeError, match='outage'):
        extract_criteria(root=root, program_id=program.id, agent=Agent(), checkpoint=True)
    preserved = load_records(root, 'live', 'programs')[0]
    assert len(preserved.criteria_extraction) == 1
    validate_store(root)
