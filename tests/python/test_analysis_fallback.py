import pytest

from pipeline.experiment import Equivalences, Equivalent, split_ask
from pipeline.llm import InvalidModelResponse, ProviderError
from pipeline.models import Generation

GEN = Generation(model='review/model', prompt_version='test', input_sha256='a' * 64)


def query(items):
    def check(result):
        if [p.pair_id for p in result.pairs] != items:
            raise ValueError('Wrong source pair')
    return 'Check equivalence', {'ids': items}, Equivalences, {'validator': check}


def response(items):
    return Equivalences(pairs=[Equivalent(pair_id=i, equivalent=False,
        rationale='Different observable actions.', left_quote=None, right_quote=None) for i in items])


def test_analysis_subdivides_before_bounded_strong_fallback():
    class Agent:
        calls = []
        def ask(self, task, data, schema, **options):
            self.calls.append((data['ids'], options.get('review', False)))
            if not options.get('review'):
                raise InvalidModelResponse('Invalid exact-source output')
            return response(data['ids']), GEN
    agent = Agent()
    results = split_ask(agent, ['aa', 'bb'], query)
    assert len(results) == 2
    assert agent.calls == [(['aa', 'bb'], False), (['aa'], False), (['aa'], True),
                           (['bb'], False), (['bb'], True)]


def test_analysis_reuses_validated_fallback():
    class Agent:
        def has_cached(self, *args, **kwargs):
            assert kwargs['review'] is True
            return True
        def ask(self, task, data, schema, **options):
            assert options['review'] is True
            return response(data['ids']), GEN
    assert len(split_ask(Agent(), ['aa'], query)) == 1


def test_stronger_model_does_not_escape_validation():
    class Agent:
        def ask(self, *args, **options):
            if not options.get('review'):
                raise InvalidModelResponse('Invalid citation')
            return response(['not-the-input']), GEN
    with pytest.raises(ValueError, match='Wrong source'):
        split_ask(Agent(), ['aa'], query)


def test_no_paid_fallback_for_provider_authentication_or_credits():
    class Agent:
        calls = 0
        def ask(self, *args, **options):
            self.calls += 1
            raise ProviderError(402, {'error': {'message': 'credits'}})
    agent = Agent()
    with pytest.raises(ProviderError):
        split_ask(agent, ['aa', 'bb'], query)
    assert agent.calls == 1
