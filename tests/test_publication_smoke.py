"""The deployment check must reject stale pages, not just HTTP 200."""
import contextlib
import hashlib
import html
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT/'tools/check_nfw_publication.py'


class PublicationSmokeTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.is_file(), 'Publication content check is missing')
        spec = importlib.util.spec_from_file_location('publication_smoke',SCRIPT)
        assert spec is not None and spec.loader is not None
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def publication_fixture(self, build_id='abc1234'):
        resources = json.loads((ROOT/'content/assets/papers/nfw-wave-optics/publication.json').read_text(encoding='utf-8'))['resources']
        payloads = {}
        for record in resources:
            path = record['path']
            if record.get('sha256'):
                payloads[path] = (ROOT/'content'/path.lstrip('/')).read_bytes()
                self.assertEqual(hashlib.sha256(payloads[path]).hexdigest(), record['sha256'])
            else:
                text = (f'<html><head><link rel="stylesheet" href="/theme/css/site.css?v={build_id}"></head>'
                        '<body>'+html.escape(' '.join(record['required_text']))+
                        f'<script src="/theme/js/site.js?v={build_id}" defer></script></body></html>')
                payloads[path] = text.encode('utf-8')
                for marker in record['required_text']:
                    self.assertIn(marker, html.unescape(text))
        self.assertEqual(sum(bool(record.get('sha256')) for record in resources), 5)
        self.assertEqual(len(resources), 19)
        return resources, payloads

    def local_fixture(self, payloads):
        fallback = (Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData/Local'))/'hermes/cache/scratch'
                    if os.name == 'nt' else Path.home()/'.hermes/cache/scratch')
        scratch = Path(os.environ.get('TMPDIR', fallback))
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix='publication-smoke-', dir=scratch)
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for path, payload in payloads.items():
            target = root/path.lstrip('/')
            if path.endswith('/'):
                target = target/'index.html'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        return root

    def run_cli(self, options):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = self.module.main(['--attempts', '1', '--delay', '0']+options)
            except SystemExit as error:
                code = error.code
        return code, stdout.getvalue(), stderr.getvalue()

    def test_old_theme_versions_with_current_content_and_downloads_are_rejected(self):
        resources, payloads = self.publication_fixture(build_id='deadbee')
        with self.assertRaisesRegex(ValueError, 'Build ID mismatch'):
            self.module.verify_resources(payloads.__getitem__, resources, expected_build_id='abc1234')

    def test_every_site_html_requires_both_exact_current_theme_versions(self):
        resources, payloads = self.publication_fixture()
        pages = [record['path'] for record in resources if not record.get('sha256')]
        self.assertEqual(len(pages), 14)
        for path in pages:
            for marker in (b'href="/theme/css/site.css?v=abc1234"', b'src="/theme/js/site.js?v=abc1234"'):
                for replacement in (marker.replace(b'abc1234', b'deadbee'), b'',
                                    marker.replace(b'abc1234', b'abc1234old')):
                    with self.subTest(path=path, marker=marker, replacement=replacement):
                        changed = dict(payloads)
                        changed[path] = payloads[path].replace(marker, replacement)
                        with self.assertRaises(ValueError) as raised:
                            self.module.verify_resources(changed.__getitem__, resources, expected_build_id='abc1234')
                        self.assertIn('Build ID mismatch at '+path+':', str(raised.exception))

    def test_all_five_download_hashes_including_standalone_html_remain_enforced(self):
        resources, payloads = self.publication_fixture()
        reading = payloads['/assets/papers/nfw-wave-optics/reading.html']
        self.assertNotIn(b'/theme/css/site.css?v=', reading)
        self.assertNotIn(b'/theme/js/site.js?v=', reading)
        self.assertEqual(self.module.verify_resources(payloads.__getitem__, resources, expected_build_id='abc1234')['status'], 'PASS')
        for record in resources:
            if record.get('sha256'):
                with self.subTest(path=record['path']):
                    changed = dict(payloads)
                    changed[record['path']] += b'changed-download'
                    with self.assertRaisesRegex(ValueError, 'Download hash mismatch'):
                        self.module.verify_resources(changed.__getitem__, resources, expected_build_id='abc1234')

    def test_full_git_sha_matches_the_first_seven_theme_version_characters(self):
        resources, payloads = self.publication_fixture()
        result = self.module.verify_resources(payloads.__getitem__, resources,
                                              expected_build_id='abc1234'+'0'*33)
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['checked_resources'], 19)

    def test_invalid_build_id_is_rejected_before_fetching(self):
        for build_id in (None, '', 'local', '123456', '12345678', 'g'*7,
                         'abc1234tail', '0'*39, '0'*41, '0'*39+'z',
                         ' abc1234', 'abc1234\n'):
            with self.subTest(build_id=build_id):
                fetch = mock.Mock(side_effect=AssertionError('fetch must not run'))
                with self.assertRaisesRegex(ValueError, 'Expected build ID'):
                    self.module.verify_resources(fetch, [], expected_build_id=build_id)
                fetch.assert_not_called()

    def test_cli_requires_explicit_valid_build_id_before_network_access(self):
        for options in ([], ['--directory', 'public'], ['--expected-build-id', 'local'],
                        ['--expected-build-id', 'abc1234tail']):
            with self.subTest(options=options):
                stderr = io.StringIO()
                outcome = None
                with mock.patch.object(self.module, 'urlopen', side_effect=AssertionError('Network forbidden')) as network:
                    with contextlib.redirect_stderr(stderr):
                        try:
                            self.module.main(['--attempts', '1', '--delay', '0']+options)
                        except Exception as error:
                            outcome = error
                        except SystemExit as error:
                            outcome = error
                    network.assert_not_called()
                self.assertIsInstance(outcome, SystemExit, 'reject invalid arguments via argparse before verification')
                self.assertEqual(getattr(outcome, 'code', None), 2)
                self.assertIn('--expected-build-id', stderr.getvalue())

    def test_cli_checks_current_build_using_full_git_sha(self):
        resources, payloads = self.publication_fixture()
        class Response(io.BytesIO):
            status = 200
        def response(request, timeout):
            return Response(payloads[urlsplit(request.full_url).path])
        stdout = io.StringIO()
        with mock.patch.object(self.module, 'urlopen', side_effect=response) as network:
            with contextlib.redirect_stdout(stdout):
                result = self.module.main(['--expected-build-id', 'abc1234'+'0'*33, '--attempts', '1', '--delay', '0'])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(stdout.getvalue())['paths'], [record['path'] for record in resources])
        self.assertEqual(network.call_count, 19)

    def test_stale_successful_response_is_rejected(self):
        resources = [{'path':'/papers/','required_text':['GPT-6.1sol Max & Hermes']}]
        with self.assertRaisesRegex(ValueError,'Missing content'):
            self.module.verify_resources(lambda path:b'<html>Old empty paper index</html>',resources,expected_build_id='abc1234')
        current = b'<p>GPT-6.1sol Max &amp; Hermes</p><link href="/theme/css/site.css?v=abc1234"><script src="/theme/js/site.js?v=abc1234"></script>'
        result = self.module.verify_resources(lambda path:current,resources,expected_build_id='abc1234')
        self.assertEqual(result['checked_resources'],1)
        self.assertEqual(result['status'],'PASS')

    def test_actions_verifies_local_artifact_before_upload_and_live_pages_with_this_sha(self):
        workflow = (ROOT/'.github/workflows/pages.yml').read_text(encoding='utf-8')
        command = 'python -B tools/check_nfw_publication.py'
        checks = [line.strip() for line in workflow.splitlines() if command in line]
        self.assertEqual(len(checks), 2, 'check both the build artifact and the deployed pages')
        for check in checks:
            self.assertIn('--expected-build-id "$GITHUB_SHA"', check)
        self.assertIn('--directory public', checks[0])
        self.assertIn('--attempts 1 --delay 0', checks[0])
        self.assertNotIn('--directory', checks[1])
        self.assertLess(workflow.index('python build.py --check'), workflow.index(checks[0]))
        self.assertLess(workflow.index(checks[0]), workflow.index('actions/upload-pages-artifact@'))

    def test_directory_checks_real_manifest_without_network(self):
        resources, payloads = self.publication_fixture()
        root = self.local_fixture(payloads)
        with mock.patch.object(self.module, 'urlopen', side_effect=AssertionError('Network forbidden')) as network:
            code, stdout, stderr = self.run_cli(['--directory', str(root), '--expected-build-id', 'abc1234'+'0'*33])
            network.assert_not_called()
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stderr, '')
        self.assertEqual(json.loads(stdout)['paths'], [record['path'] for record in resources])

    def test_directory_rejects_stale_missing_or_corrupt_resources_without_network_fallback(self):
        resources, payloads = self.publication_fixture()
        for failure, message in (('stale', 'Build ID mismatch'), ('missing', 'Attempt 1:'),
                                 ('corrupt', 'Download hash mismatch')):
            with self.subTest(failure=failure):
                changed = dict(payloads)
                if failure == 'stale':
                    changed['/zh/writing/nfw-wave-optics-lessons/'] = changed['/zh/writing/nfw-wave-optics-lessons/'].replace(b'?v=abc1234', b'?v=deadbee')
                elif failure == 'missing':
                    del changed['/papers/nfw-wave-optics/']
                else:
                    changed['/assets/papers/nfw-wave-optics/reading.html'] += b'changed-download'
                root = self.local_fixture(changed)
                with mock.patch.object(self.module, 'urlopen', side_effect=AssertionError('Network forbidden')) as network:
                    code, stdout, stderr = self.run_cli(['--directory', str(root), '--expected-build-id', 'abc1234'])
                    network.assert_not_called()
                self.assertEqual(code, 1, stderr)
                self.assertEqual(stdout, '')
                self.assertIn(message, stderr)

    def test_replaced_download_is_rejected(self):
        import hashlib
        spec = importlib.util.spec_from_file_location('publication_smoke',SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        current = b'%PDF-test-fixture-current'
        resources = [{'path':'/paper.pdf','sha256':hashlib.sha256(current).hexdigest()}]
        with self.assertRaisesRegex(ValueError,'Download hash mismatch'):
            module.verify_resources(lambda path:b'%PDF-test-fixture-previous',resources,expected_build_id='abc1234')
        self.assertEqual(module.verify_resources(lambda path:current,resources,expected_build_id='abc1234')['status'],'PASS')


if __name__ == '__main__':
    unittest.main()
