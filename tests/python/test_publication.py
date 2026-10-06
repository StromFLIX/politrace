"""Publication must use the current checkout, not schemas cached before a rebase."""
import importlib.util
import json
import subprocess
import sys

import pytest

from scripts import publish_data


@pytest.fixture
def publisher(tmp_path, monkeypatch):
    config = tmp_path / '.github/production.json'
    config.parent.mkdir()
    config.write_text(json.dumps({'publication': 'main'}))
    monkeypatch.setattr(publish_data, 'ROOT', tmp_path)
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/main')
    events = []
    state = {'changed': True, 'push_code': 0, 'invalid_after_rebase': False,
             'conflict': False, 'validations': 0}

    def git(*args, **kwargs):
        events.append(('git', *args))
        if args[0] == 'rebase' and state['conflict']:
            raise subprocess.CalledProcessError(1, ['git', *args])
        return subprocess.CompletedProcess(['git', *args], 0)

    def run(command, **kwargs):
        events.append(tuple(command))
        if command[:2] == ['uv', 'run']:
            assert command == ['uv', 'run', '--frozen', 'python', '-m', 'pipeline.cli', 'validate']
            assert kwargs == {'cwd': tmp_path, 'check': True}
            state['validations'] += 1
            if state['validations'] > 1 and state['invalid_after_rebase']:
                raise subprocess.CalledProcessError(1, command)
            return subprocess.CompletedProcess(command, 0)
        if command == ['git', 'diff', '--cached', '--quiet']:
            return subprocess.CompletedProcess(command, int(state['changed']))
        if command[0] == 'git' and 'push' in command:
            assert command[-3:] == ['push', 'origin', 'HEAD:refs/heads/main']
            assert '--force' not in command
            return subprocess.CompletedProcess(command, state['push_code'])
        assert command == ['gh', 'workflow', 'run', 'ci.yml', '--ref', 'main']
        assert kwargs['check'] is True
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(publish_data, 'git', git)
    monkeypatch.setattr(publish_data.subprocess, 'run', run)
    return events, state


def test_rebase_validates_new_code_before_push_and_ci(publisher):
    events, state = publisher
    publish_data.main()
    assert state['validations'] == 2
    rebase = events.index(('git', 'rebase', 'origin/main'))
    assert events[rebase + 1] == ('uv', 'run', '--frozen', 'python', '-m', 'pipeline.cli', 'validate')
    assert 'push' in events[rebase + 2]
    assert events[-1] == ('gh', 'workflow', 'run', 'ci.yml', '--ref', 'main')


def test_new_contract_failure_blocks_push_not_just_initial_validation(publisher):
    events, state = publisher
    state['invalid_after_rebase'] = True
    with pytest.raises(subprocess.CalledProcessError):
        publish_data.main()
    assert state['validations'] == 2
    assert not any('push' in event or event[0] == 'gh' for event in events)


def test_no_changes_do_not_commit_push_or_dispatch(publisher):
    events, state = publisher
    state['changed'] = False
    publish_data.main()
    assert state['validations'] == 1
    assert not any('commit' in event or 'push' in event or event[0] == 'gh' for event in events)


def test_conflicting_citizen_edits_stop_publication(publisher):
    events, state = publisher
    state['conflict'] = True
    with pytest.raises(subprocess.CalledProcessError):
        publish_data.main()
    assert not any('push' in event or event[0] == 'gh' for event in events)


def test_push_retries_are_bounded_and_revalidate_each_new_checkout(publisher):
    events, state = publisher
    state['push_code'] = 1
    with pytest.raises(RuntimeError, match='never force-push'):
        publish_data.main()
    assert state['validations'] == 4
    assert events.count(('git', 'fetch', 'origin', 'main')) == 3
    assert not any(event[0] == 'gh' for event in events)


def test_publication_outside_main_is_refused(publisher, monkeypatch):
    events, _ = publisher
    monkeypatch.setenv('GITHUB_REF', 'refs/heads/untrusted')
    with pytest.raises(RuntimeError, match='restricted'):
        publish_data.main()
    assert events == []


def test_fresh_validator_sees_schema_changed_after_import(tmp_path, monkeypatch):
    """Reproduce the cached old Vote contract without network, Git or model calls."""
    package = tmp_path / 'pipeline'
    package.mkdir()
    (package / '__init__.py').write_text('')
    contract = package / 'models.py'
    contract.write_text('def validate(record):\n    assert set(record) == {"id"}\n')
    spec = importlib.util.spec_from_file_location('previous_contract', contract)
    stale = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stale)
    (package / 'cli.py').write_text(
        'import json, sys\n'
        'from pathlib import Path\n'
        'from pipeline.models import validate\n'
        'assert sys.argv[1:] == ["validate"]\n'
        'validate(json.loads(Path("vote.json").read_text()))\n'
    )
    (tmp_path / 'vote.json').write_text('{"id": "vote", "stage": "second_reading"}')
    contract.write_text('def validate(record):\n    assert set(record) == {"id", "stage"}\n')
    with pytest.raises(AssertionError):
        stale.validate({'id': 'vote', 'stage': 'second_reading'})
    monkeypatch.setattr(publish_data, 'ROOT', tmp_path)
    monkeypatch.setenv('UV_PYTHON', sys.executable)
    monkeypatch.setenv('UV_OFFLINE', '1')
    monkeypatch.delenv('PYTHONPATH', raising=False)
    publish_data.validate_checkout()
    # A fresh process must still reject a genuinely invalid merged record.
    (tmp_path / 'vote.json').write_text('{"id": "vote", "unsupported": true}')
    with pytest.raises(subprocess.CalledProcessError):
        publish_data.validate_checkout()
