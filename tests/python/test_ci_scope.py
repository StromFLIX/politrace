"""Check selection must fail closed when publication rebases over untested code."""
import subprocess
from pathlib import Path

import pytest

from scripts import ci_scope


@pytest.fixture
def repository(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    subprocess.run(['git', 'init', '--quiet'], check=True)
    # Temporary fixture repositories must work on clean Actions runners too.
    # This does not change the real repository's configured authorship or hooks.
    subprocess.run(['git', 'config', '--local', 'user.name', 'CI scope fixture'], check=True)
    subprocess.run(['git', 'config', '--local', 'user.email', 'ci-scope@example.invalid'], check=True)

    def commit(path, content='version one'):
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        subprocess.run(['git', 'add', '--all'], check=True)
        subprocess.run(['git', 'commit', '--quiet', '-m', 'Scope fixture'], check=True)
        return subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()

    return commit


def test_no_hints_or_history_runs_every_check():
    assert ci_scope.select_checks()['full_code'] == 'true'
    assert ci_scope.select_checks()['container'] == 'true'


@pytest.mark.parametrize('revision', ['main', 'HEAD', '--help', 'a' * 39, '0' * 40, 'f' * 40])
def test_invalid_or_unavailable_publisher_revision_never_skips_code(repository, revision):
    repository('src/page.astro')
    checks = ci_scope.select_checks(revision)
    assert checks['full_code'] == checks['container'] == 'true'


def test_only_publisher_validated_data_changes_skip_repeated_code(repository):
    tested = repository('src/page.astro')
    repository('data/live/criteria/example.json', '{}')
    assert ci_scope.select_checks(tested)['full_code'] == 'false'
    assert ci_scope.select_checks(tested)['container'] == 'false'
    # Ordinary data pushes do not assert the code was already tested.
    assert ci_scope.select_checks(base_revision=tested)['full_code'] == 'true'


@pytest.mark.parametrize('path', ['src/page.astro', 'pipeline/models.py', 'data/schemas/law.json',
                                 'data/parties.json', 'data/live-other/file.json',
                                 '.github/workflows/production.yml'])
def test_concurrent_rebase_changes_outside_live_data_require_full_code(repository, path):
    tested = repository('initial.txt')
    repository(path, 'concurrent change')
    repository('data/live/laws/new.json', '{}')
    assert ci_scope.select_checks(tested)['full_code'] == 'true'


@pytest.mark.parametrize('path', sorted(ci_scope.CONTAINER_INPUTS) + ['deploy/nginx.conf'])
def test_packaging_changes_always_rebuild_container(repository, path):
    base = repository('initial.txt')
    repository(path)
    checks = ci_scope.select_checks(base_revision=base)
    assert checks['full_code'] == checks['container'] == 'true'


@pytest.mark.parametrize('path', ['src/page.astro', 'data/live/criteria/new.json',
                                 'pipeline/models.py', 'docs/deployment.md'])
def test_unrelated_changes_keep_code_checks_without_rebuilding_container(repository, path):
    base = repository('initial.txt')
    repository(path)
    checks = ci_scope.select_checks(base_revision=base)
    assert checks['full_code'] == 'true'
    assert checks['container'] == 'false'


def test_nonancestor_revision_is_not_a_validated_baseline(repository):
    base = repository('initial.txt')
    other = repository('src/untested.astro')
    subprocess.run(['git', 'checkout', '--quiet', '--detach', base], check=True)
    repository('data/live/new.json', '{}')
    assert ci_scope.changed_paths(other) is None
    assert ci_scope.select_checks(other)['full_code'] == 'true'


def test_rename_into_live_data_cannot_hide_code_removal(repository):
    tested = repository('src/example.json', '{}')
    Path('data/live').mkdir(parents=True)
    Path('src/example.json').rename('data/live/example.json')
    repository('data/live/another.json', '{}')
    assert ci_scope.select_checks(tested)['full_code'] == 'true'


def test_outputs_and_summary_explain_optimized_publication(repository, tmp_path, monkeypatch):
    tested = repository('initial.txt')
    repository('data/live/example.json', '{}')
    output, summary = tmp_path / 'output', tmp_path / 'summary'
    monkeypatch.setenv('VALIDATED_REVISION', tested)
    monkeypatch.setenv('GITHUB_OUTPUT', str(output))
    monkeypatch.setenv('GITHUB_STEP_SUMMARY', str(summary))
    ci_scope.main()
    assert output.read_text() == 'full_code=false\ncontainer=false\n'
    assert 'Publisher-tested code unchanged' in summary.read_text()
