import json
import urllib.error

import pytest

from scripts.verify_deployment import (
    SnapshotMismatch,
    expected_snapshot,
    verify_once,
    wait_for_deployment,
)

EXPECTED = {'/api/v1/live/index.json': b'{"data_sha256":"same-political-data"}',
            '/api/v1/live/readings.json': b'{"reading":"new-ocr"}',
            '/fortschritt/': b'<html>new-progress-and-assets</html>'}
BASE = 'https://politrace.example'


def serving(expected=EXPECTED):
    def request(url):
        path = url.removeprefix(BASE)
        return (200, expected[path]) if path in expected else (404, b'')
    return request


def test_exact_snapshot_and_retired_route_404s():
    verify_once(BASE, EXPECTED, request=serving())


def test_same_political_digest_does_not_mask_old_ocr_or_old_layout():
    for path in ('/api/v1/live/readings.json', '/fortschritt/'):
        with pytest.raises(SnapshotMismatch, match='differs'):
            verify_once(BASE, EXPECTED, request=serving({**EXPECTED, path: b'old-version'}))


def test_catch_all_200_and_demo_routes_are_not_accepted():
    def request(url):
        status, data = serving()(url)
        return (200, b'catch-all-page') if status == 404 else (status, data)
    with pytest.raises(SnapshotMismatch, match='expected a genuine 404'):
        verify_once(BASE, EXPECTED, request=request)


def test_snapshot_change_mid_verification_is_not_a_success():
    calls = 0
    def request(url):
        nonlocal calls
        calls += 1
        if calls == len(EXPECTED) + 4:
            return 200, b'newer-snapshot'
        return serving()(url)
    with pytest.raises(SnapshotMismatch, match='changed during verification'):
        verify_once(BASE, EXPECTED, request=request)


def test_waits_for_delayed_deployment_without_logging_provider_bodies():
    now, logs = [0], []
    def request(url):
        if now[0] == 0:
            raise urllib.error.URLError('private upstream diagnostics')
        if now[0] == 1:
            return 200, b'private response from old site'
        return serving()(url)
    wait_for_deployment(BASE, EXPECTED, interval=1, timeout=4, request=request,
                        clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s), report=logs.append)
    assert now[0] == 2
    assert 'Verified exact deployed snapshot' in logs[-1]
    assert 'private' not in '\n'.join(logs)


def test_undeployed_build_fails_with_bounded_wait():
    now = [0]
    with pytest.raises(SnapshotMismatch, match='not verified within 3s'):
        wait_for_deployment(BASE, EXPECTED, interval=1, timeout=3, request=lambda _: (503, b''),
                            clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s), report=lambda _: None)
    assert now[0] == 3


@pytest.mark.parametrize('url', ['http://politrace.example', 'https://key:secret@politrace.example',
                                'https://politrace.example?token=secret', 'https://politrace.example/path'])
def test_no_insecure_or_credential_bearing_urls(url):
    with pytest.raises(ValueError):
        wait_for_deployment(url, EXPECTED)


def test_build_expectations_include_all_programmes_and_a_law(tmp_path):
    items = [{'document_id': 'first-2025', 'collection': 'programs'},
             {'document_id': 'second-2025', 'collection': 'programs'},
             {'document_id': 'bgbl-1-2025-1', 'collection': 'laws'}]
    paths = ['api/v1/live/index.json', 'api/health.json', 'api/v1/live/analysis.json',
             'api/v1/live/reading-progress.json', 'index.html', 'fortschritt/index.html',
             'live/programme/first-2025/index.html', 'live/programme/second-2025/index.html',
             'live/gesetze/bgbl-1-2025-1/index.html']
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('public expected artifact')
    (tmp_path / 'api/v1/live/readings.json').write_text(json.dumps({'items': items}))
    result = expected_snapshot(tmp_path)
    assert '/live/programme/first-2025/' in result and '/live/programme/second-2025/' in result
    assert '/live/gesetze/bgbl-1-2025-1/' in result


def test_ci_checks_public_snapshot_and_browsers_only_on_main():
    from pathlib import Path
    workflow = Path('.github/workflows/ci.yml').read_text()
    assert "github.ref == 'refs/heads/main' && github.event_name != 'pull_request'" in workflow
    assert 'scripts/verify_deployment.py' in workflow
    assert 'POLITRACE_TEST_BASE_URL: https://politrace.stromflix.com' in workflow
