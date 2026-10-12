"""Conservatively select repeated code/container checks; always test published data.

Only the trusted production publisher supplies VALIDATED_REVISION, the checkout
whose code it already tested. Git must prove that *every* subsequent change is
under data/live. Missing history, concurrent code changes and malformed inputs
fall back to full checks. Ordinary pushes/PRs never skip code tests.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

CONTAINER_INPUTS = {
    'Dockerfile', '.dockerignore', 'docker-compose.yml', 'docker-compose.local.yml',
    'package.json', 'package-lock.json', 'astro.config.mjs', 'tsconfig.json',
    '.github/workflows/ci.yml', 'scripts/ci_scope.py',
}


def changed_paths(base: str) -> list[str] | None:
    if not re.fullmatch(r'[0-9a-f]{40}', base) or base == '0' * 40:
        return None
    ancestor = subprocess.run(['git', 'merge-base', '--is-ancestor', base, 'HEAD'],
                              capture_output=True)
    if ancestor.returncode:
        return None
    result = subprocess.run(['git', 'diff', '--name-only', '--no-renames', '-z', base, 'HEAD'],
                            capture_output=True)
    if result.returncode:
        return None
    return result.stdout.decode().rstrip('\0').split('\0') if result.stdout else []


def select_checks(validated_revision: str = '', base_revision: str = '') -> dict[str, str]:
    validated = changed_paths(validated_revision) if validated_revision else None
    if validated is not None and all(path.startswith('data/live/') for path in validated):
        return {'full_code': 'false', 'container': 'false',
                'reason': 'Publisher-tested code unchanged; validating/building/browser-testing new data.'}
    changed = changed_paths(base_revision) if base_revision else None
    container = changed is None or any(path in CONTAINER_INPUTS or path.startswith('deploy/')
                                       for path in changed)
    return {'full_code': 'true', 'container': str(container).lower(),
            'reason': 'Full code checks; container rebuild only when packaging inputs change.'}


def main():
    checks = select_checks(os.environ.get('VALIDATED_REVISION', ''),
                           os.environ.get('BASE_REVISION', ''))
    print(checks['reason'])
    with Path(os.environ['GITHUB_OUTPUT']).open('a') as output:
        for key in ('full_code', 'container'):
            output.write(f'{key}={checks[key]}\n')
    if summary := os.environ.get('GITHUB_STEP_SUMMARY'):
        with Path(summary).open('a') as output:
            output.write(f"### CI scope\n{checks['reason']}\n")


if __name__ == '__main__':
    main()
