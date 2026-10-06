"""Publish validated final agent assessments; respect branch protection and citizen edits."""
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def validate_checkout():
    """Load the checked-out contracts in a fresh process, including after rebase."""
    # A concurrent code/schema commit can replace modules already imported by the
    # publisher. Reloading one module is not enough: Pydantic models and validators
    # can still refer to the old classes. uv also syncs the current frozen lockfile.
    subprocess.run(['uv', 'run', '--frozen', 'python', '-m', 'pipeline.cli', 'validate'],
                   cwd=ROOT, check=True)


def git(*args, **kwargs):
    return subprocess.run(['git', '-c', 'credential.helper=', '-c',
                           'credential.helper=!gh auth git-credential', *args],
                          cwd=ROOT, check=True, **kwargs)


def main():
    config = json.loads((ROOT / '.github/production.json').read_text())
    if config['publication'] != 'main' or os.environ.get('GITHUB_REF') != 'refs/heads/main':
        raise RuntimeError('Automatic publication is restricted to the configured main-branch proposal channel')
    validate_checkout()
    git('add', '--', 'data/live')
    changed = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT).returncode
    if not changed:
        print('No canonical change: no commit, deployment or empty PR')
        return
    git('commit', '-m', 'data: publish final agent assessments and source checkpoint')
    git('log', '-1', '--format=full')
    for attempt in range(3):
        git('fetch', 'origin', 'main')
        # Only the new data commit is replayed; Git refuses conflicting citizen edits.
        git('rebase', 'origin/main')
        validate_checkout()
        result = subprocess.run(['git', '-c', 'credential.helper=', '-c',
                                 'credential.helper=!gh auth git-credential',
                                 'push', 'origin', 'HEAD:refs/heads/main'], cwd=ROOT)
        if result.returncode == 0:
            # GITHUB_TOKEN pushes suppress Actions push triggers. Dispatch CI explicitly.
            # The installed Coolify GitHub App receives the push; CI verifies its exact
            # public deployment as well as the build. No branch protection bypass.
            subprocess.run(['gh', 'workflow', 'run', 'ci.yml', '--ref', 'main'], check=True)
            print('Published final source/analysis snapshot; CI explicitly dispatched')
            return
        if attempt == 2:
            raise RuntimeError('Push rejected; checkpoint remains downloadable, never force-push')


if __name__ == '__main__':
    main()
