import pytest

from pipeline.citations import source_quote


def test_restores_only_original_whitespace_and_retains_verbatim_span():
    source = 'Vorwort. Wir erhöhen\nden Mindestlohn auf\n\n15\u00a0Euro. Nachwort.'
    exact = source_quote('Wir erhöhen den Mindestlohn auf 15 Euro.', source)
    assert exact == 'Wir erhöhen\nden Mindestlohn auf\n\n15\u00a0Euro.'
    assert exact in source


def test_already_exact_quotes_are_unchanged_even_if_repeated():
    quote = 'Dies ist ein genaues Zitat.'
    assert source_quote(quote, quote + '\n' + quote) == quote


@pytest.mark.parametrize('quote', [
    'Wir senken den Mindestlohn auf 15 Euro.',
    'Wir erhöhen den Mindestlohn auf 16 Euro.',
    'Wir erhöhen den Mindestlohn auf 15 Euro',  # no period is a valid exact substring
])
def test_changed_words_and_numbers_never_get_repaired(quote):
    source = 'Wir erhöhen\nden Mindestlohn auf 15 Euro.'
    if quote.endswith('15 Euro'):
        assert source_quote(quote, source) == source[:-1]
    else:
        with pytest.raises(ValueError):
            source_quote(quote, source)


@pytest.mark.parametrize('quote,source', [
    ('Wir wollen 10000 Euro.', 'Wir wollen 10 000 Euro.'),
    ('Wir wollen das umsetzen.', 'Wir wollen das **umsetzen**.'),
    ('Wir wollen das umsetzen.', 'wir wollen das umsetzen.'),
    ('Wir wollen umsetzen.', 'Wir wollen nicht umsetzen.'),
    ('Eine vollständige Bedingung.', 'Eine voll-\nständige Bedingung.'),
    (' ', ''), (None, ''), (' ' * 40, ' ' * 40),
])
def test_never_changes_word_boundaries_case_punctuation_markdown_or_negation(quote, source):
    with pytest.raises(ValueError):
        source_quote(quote, source)


def test_ambiguous_whitespace_normalized_occurrences_fail():
    source = 'Eine lange\nForderung. Eine lange\tForderung.'
    with pytest.raises(ValueError, match='ambiguous'):
        source_quote('Eine lange Forderung.', source)


def test_validator_saves_the_reanchored_source_not_the_model_formatting(corpus):
    from pipeline.models import Generation
    from pipeline.programs import extract_criteria
    from pipeline.store import load_records
    root, program, criterion, _ = corpus
    (root / f'live/criteria/{criterion.id}.json').unlink()
    # Source remains untouched; add line breaks in the model's copy only.
    class Agent:
        def ask(self, task, data, schema, **options):
            replies = []
            for p in data['paragraphs']:
                replies.append({'leaf_id': p['leaf_id'], 'abstention_reason': None,
                    'criteria': [{'title': 'Eine überprüfbare Forderung', 'description': 'Ein Test mit Quellenbeleg.',
                        'test': 'Eine überprüfbare Testbedingung.', 'quote': p['paragraph'].replace(' ', '\n'),
                        'tags': ['arbeit'], 'keywords': [], 'deadline': None}]})
            response = schema.model_validate({'paragraphs': replies})
            options['validator'](response)
            return response, Generation(model='test/model', prompt_version='test', input_sha256='a' * 64)
    extract_criteria(root=root, program_id=program.id, agent=Agent(), batch_size=4)
    leaves = {leaf.id: leaf for leaf in program.leaves}
    for record in load_records(root, 'live', 'criteria'):
        assert record.reference.quote in leaves[record.leaf_id].text
        assert record.reference.quote == leaves[record.leaf_id].text
