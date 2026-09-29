import contextlib
import gzip
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs

SPEC = importlib.util.spec_from_file_location('wayback', Path(__file__).resolve().parents[1] / 'export-wayback-snapshots.py')
w = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(w)
SITE = 'https://vojtamaur.cz'
NS = w.SITEMAP_NS
IMG = w.IMAGE_NS


class WaybackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dist = Path(self.tmp.name)

    def write(self, file, content):
        target = self.dist / file
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode())

    def fixture(self):
        self.write('sitemap-index.xml', f'<sitemapindex xmlns="{NS}"><sitemap><loc>{SITE}/nested.xml.gz</loc></sitemap><sitemap><loc>{SITE}/broken.xml</loc></sitemap></sitemapindex>')
        self.write('nested.xml.gz', gzip.compress(f'<sitemapindex xmlns="{NS}"><sitemap><loc>{SITE}/sitemap-index.xml</loc></sitemap><sitemap><loc>{SITE}/pages.xml</loc></sitemap></sitemapindex>'.encode()))
        self.write('pages.xml', f'''<urlset xmlns="{NS}" xmlns:image="{IMG}" xmlns:video="urn:video">
        <url><loc>{SITE}/ns/</loc><image:image><image:loc>{SITE}/images/photo.jpg#one</image:loc></image:image><video:loc>{SITE}/ignore.mp4</video:loc></url>
        <url><loc>{SITE}/en/post/</loc><image:image><image:loc>https://VOJTAMAUR.cz:443/images/%70hoto.jpg</image:loc></image:image></url>
        <url><loc>{SITE}/images/photo.jpg</loc></url>
        <url><loc>{SITE}/files/a.pdf?download=1&amp;x=2</loc></url>
        <url><loc>{SITE}/ALL_POSTS.txt</loc></url></urlset>''')
        self.write('broken.xml', '<broken')

    def test_nested_gzip_cycles_dedup_types_and_partial_failure(self):
        self.fixture()
        with patch.object(w, 'request_bytes', side_effect=AssertionError('network')):
            urls, errors = w.collect_urls(dist=self.dist)
        self.assertEqual(errors, 1)
        self.assertEqual(len(urls), 5)
        self.assertEqual(urls.count(SITE + '/images/photo.jpg'), 1)
        self.assertIn(SITE + '/ns/', urls)
        self.assertIn(SITE + '/files/a.pdf?download=1&x=2', urls)
        for kind, count in [('pages', 2), ('images', 1), ('pdf', 1), ('txt', 1)]:
            selected, _ = w.collect_urls(dist=self.dist, types=[kind])
            self.assertEqual(len(selected), count)

    def test_legacy_namespace_free_sitemap(self):
        self.write('sitemap-index.xml', f'<urlset><url><loc>{SITE}/ns/</loc></url></urlset>')
        self.assertEqual(w.collect_urls(dist=self.dist), ([SITE + '/ns/'], 0))

    def test_invalid_inputs_and_redirects(self):
        for value in ['file:///etc/passwd', '//vojtamaur.cz/a', 'javascript:alert(1)',
                      'https://u:p@vojtamaur.cz/', 'http://127.0.0.1/', 'http://[::1]/',
                      'https://localhost/', 'https://10.0.0.1/', 'https://host.local/',
                      SITE + ':bad/', SITE + '/a\nb', SITE + '/%00', SITE + '/%zz',
                      SITE + '/%2e%2e%2fsecret', SITE + '/x\\y']:
            with self.subTest(value=value), self.assertRaises(w.ExportError):
                w.validate_url(value)
        self.assertEqual(w.validate_url('https://VOJTAMAUR.cz:443/a#x'), SITE + '/a')
        with self.assertRaises(w.ExportError):
            w.SitemapRedirect(SITE).redirect_request(None, None, 302, '', {}, 'http://127.0.0.1/a')

    def test_bad_entries_do_not_become_capture_targets(self):
        self.write('sitemap-index.xml', f'<urlset xmlns="{NS}" xmlns:image="{IMG}"><url><loc>{SITE}/</loc><image:image><image:loc>https://evil.example/x.jpg</image:loc></image:image></url><url><loc>file:///a</loc></url><url/></urlset>')
        urls, errors = w.collect_urls(dist=self.dist)
        self.assertEqual(urls, [SITE + '/'])
        self.assertEqual(errors, 3)

    def test_dry_run_has_no_credentials_network_capture_or_output(self):
        self.write('sitemap-index.xml', f'<urlset><url><loc>{SITE}/a.pdf</loc></url></urlset>')
        with patch.object(sys, 'argv', ['export', '--dry-run', '--dist', str(self.dist), '--types', 'pdf']), patch.object(w, 'capture', side_effect=AssertionError('capture')), patch.object(w, 'request_bytes', side_effect=AssertionError('network')), patch.object(w, 'EXPORT_DIR', self.dist / 'output'), patch.dict(w.os.environ, {}, clear=True), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(w.main(), 0)
            self.assertEqual(output.getvalue().strip(), SITE + '/a.pdf')
            self.assertFalse((self.dist / 'output').exists())

    def test_cli_validation(self):
        for options in [['--dist', str(self.dist)], ['--delay', '0'], ['--delay', 'nan'], ['--limit', '0'], ['--if-not-archived-within', '-1']]:
            with self.subTest(options=options), patch.object(sys, 'argv', ['export'] + options), self.assertRaises(SystemExit) as exc:
                w.main()
            self.assertEqual(exc.exception.code, 2)

    def success(self, url):
        return {'status': 'success', 'timestamp': '20260928123456', 'original_url': url}

    def test_binary_capture_polls_one_job_and_uses_force_get(self):
        for suffix in ['jpg', 'pdf', 'txt']:
            url = SITE + '/file.' + suffix
            with patch.object(w, 'api_json', side_effect=[{'job_id': 'job'}, {'status': 'pending'}, self.success(url)]) as api, patch.object(w.time, 'sleep'):
                self.assertIn(url, w.capture(None, 'SECRET', url))
                self.assertEqual(api.call_args_list[0].args[3]['force_get'], '1')
                self.assertEqual(sum(len(c.args) == 4 for c in api.call_args_list), 1)
                self.assertNotIn('capture_all', api.call_args_list[0].args[3])

    def test_post_errors_never_retry(self):
        for error in [URLError('lost reply'), HTTPError(w.SAVE_URL, 500, 'server', {}, None)]:
            opener = Mock()
            opener.open.side_effect = error
            with patch.object(w.time, 'sleep'), self.assertRaises(w.ExportError):
                w.request_bytes(opener, w.SAVE_URL, data=b'url=x', authorization='SECRET')
            self.assertEqual(opener.open.call_count, 1)

    def test_get_retry_after_and_no_auth_on_sitemaps(self):
        opener = Mock()
        response = Mock()
        response.read.return_value = b'ok'
        response.headers = {}
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener.open.side_effect = [HTTPError(SITE, 429, 'rate', {'Retry-After': '120'}, None), response]
        with patch.object(w.time, 'sleep') as sleep:
            self.assertEqual(w.request_bytes(opener, SITE), b'ok')
            sleep.assert_called_once_with(120)
        self.assertNotIn('Authorization', opener.open.call_args.args[0].headers)

    def test_terminal_failure_favicon_and_timeout_never_resubmit(self):
        results = [{'status': 'error', 'status_ext': code} for code in
                   ['error:cannot-fetch', 'error:gateway-timeout', 'error:no-captures', 'nocaptures']]
        for result in results + [self.success(SITE + '/favicon.ico')]:
            with patch.object(w, 'api_json', return_value=result) as api, self.assertRaises(w.ExportError):
                w.capture(None, 'SECRET', SITE + '/post/')
            self.assertEqual(api.call_count, 1)
        with patch.object(w, 'api_json', return_value={'job_id': 'x'}) as api, patch.object(w.time, 'monotonic', side_effect=[0, 100]), self.assertRaises(w.ExportError):
            w.capture(None, 'SECRET', SITE + '/', poll_timeout=5)
        self.assertEqual(api.call_count, 1)

    def test_retry_after_cannot_overrun_polling_deadline(self):
        opener = Mock()
        opener.open.side_effect = HTTPError(w.SAVE_URL, 429, 'rate', {'Retry-After': '120'}, None)
        with patch.object(w.time, 'monotonic', return_value=10), patch.object(w.time, 'sleep') as sleep, self.assertRaises(w.RateLimited):
            w.request_bytes(opener, w.SAVE_URL + '/status/job', authorization='SECRET', deadline=30)
        sleep.assert_not_called()
        self.assertEqual(opener.open.call_count, 1)

    def test_rate_limit_stops_batch_and_preserves_completed_lines(self):
        urls = [SITE + '/a', SITE + '/b', SITE + '/c']
        with patch.object(sys, 'argv', ['export']), patch.dict(w.os.environ, {'IA_ACCESS_KEY_ID': 'key', 'IA_SECRET_ACCESS_KEY': 'secret'}), patch.object(w, 'collect_urls', return_value=(urls, 0)), patch.object(w, 'capture', side_effect=['https://web.archive.org/web/20260928123456/' + urls[0], w.RateLimited('quota')]) as capture, patch.object(w.time, 'sleep'), patch.object(w, 'EXPORT_DIR', self.dist):
            self.assertEqual(w.main(), 1)
            self.assertEqual(capture.call_count, 2)
        files = list(self.dist.glob('*.txt'))
        self.assertEqual(len(files), 1)
        self.assertEqual(len(files[0].read_text().splitlines()), 1)

    def response(self, body):
        response = Mock()
        response.read.return_value = json.dumps(body).encode()
        response.headers = {}
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def test_pasted_429_waits_then_submits_rejected_request(self):
        opener = Mock()
        opener.open.side_effect = [HTTPError(w.SAVE_URL, 429, 'rate', {'Retry-After': '300'}, io.BytesIO(b'{}')), self.response({'job_id': 'accepted'}), self.response(self.success(SITE + '/a.jpg'))]
        with patch.object(w.time, 'sleep') as sleep:
            self.assertIn('/a.jpg', w.capture(opener, 'SECRET', SITE + '/a.jpg'))
        self.assertEqual(sleep.call_args_list[0].args, (300,))
        methods = [call.args[0].get_method() for call in opener.open.call_args_list]
        self.assertEqual(methods, ['POST', 'POST', 'GET'])

    def test_429_exhaustion_stops_and_honors_longer_retry_after(self):
        opener = Mock()
        opener.open.side_effect = [HTTPError(w.SAVE_URL, 429, 'rate', {'Retry-After': '600'}, io.BytesIO(b'{}')) for _ in range(w.MAX_RETRIES + 1)]
        with patch.object(w.time, 'sleep') as sleep, self.assertRaises(w.RateLimited):
            w.capture(opener, 'SECRET', SITE + '/')
        self.assertEqual(sleep.call_count, w.MAX_RETRIES)
        self.assertTrue(all(call.args[0] >= 600 for call in sleep.call_args_list))

    def test_429_with_accepted_job_never_resubmits(self):
        opener = Mock()
        opener.open.side_effect = [HTTPError(w.SAVE_URL, 429, 'rate', {}, io.BytesIO(b'{"job_id":"already-accepted"}')), self.response(self.success(SITE + '/'))]
        with patch.object(w.time, 'sleep'):
            w.capture(opener, 'SECRET', SITE + '/')
        self.assertEqual([call.args[0].get_method() for call in opener.open.call_args_list], ['POST', 'GET'])

    def test_per_url_daily_limit_does_not_stop_other_targets(self):
        result = {'status': 'error', 'status_ext': 'error:too-many-daily-captures', 'message': 'This URL has been already captured 1 times today'}
        with patch.object(w, 'api_json', return_value=result) as api:
            with self.assertRaises(w.ExportError) as exc:
                w.capture(None, 'SECRET', SITE + '/a.jpg')
            self.assertNotIsInstance(exc.exception, w.RateLimited)
        self.assertEqual(api.call_count, 1)

    def test_session_admission_rejection_retries_but_accepted_job_does_not(self):
        rejection = {'status': 'error', 'status_ext': 'error:user-session-limit'}
        with patch.object(w, 'api_json', side_effect=[rejection, self.success(SITE + '/')]) as api, patch.object(w.time, 'sleep') as sleep:
            w.capture(None, 'SECRET', SITE + '/')
        self.assertEqual(api.call_count, 2)
        sleep.assert_called_once_with(300)
        with patch.object(w, 'api_json', return_value={**rejection, 'job_id': 'accepted'}) as api, self.assertRaises(w.RateLimited):
            w.capture(None, 'SECRET', SITE + '/')
        self.assertEqual(api.call_count, 1)

    def test_recent_exports_ignore_old_future_malformed_and_use_newest(self):
        now = datetime(2026, 9, 29, tzinfo=timezone.utc)
        self.write('vojtamaur-web-wayback-old.txt', '\n'.join([
            'https://web.archive.org/web/20260928010000/' + SITE + '/a.jpg',
            'https://web.archive.org/web/20260928235900/' + SITE + '/a.jpg',
            'https://web.archive.org/web/20260927000000/' + SITE + '/old',
            'https://web.archive.org/web/20990101000000/' + SITE + '/future',
            'https://web.archive.org/web/20260928230000/http://127.0.0.1/',
            'https://web.archive.org/web/20261328230000/' + SITE + '/bad-date',
            'malformed',
        ]))
        recent = w.recent_snapshots(self.dist, 86400, now=now)
        self.assertEqual(list(recent), [SITE + '/a.jpg'])
        self.assertIn('/20260928235900/', recent[SITE + '/a.jpg'])
        self.assertEqual(w.recent_snapshots(self.dist, 0, now=now), {})

    def test_restart_reuses_prior_success_and_continues_after_failure(self):
        stamp = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime('%Y%m%d%H%M%S')
        old = f'https://web.archive.org/web/{stamp}/{SITE}/a.jpg'
        self.write('vojtamaur-web-wayback-previous.txt', old + '\n')
        urls = [SITE + '/a.jpg', SITE + '/b.jpg', SITE + '/c.jpg']
        with patch.object(sys, 'argv', ['export', '--with-files']), patch.dict(w.os.environ, {'IA_ACCESS_KEY_ID': 'key', 'IA_SECRET_ACCESS_KEY': 'secret'}), patch.object(w, 'collect_urls', return_value=(urls, 0)), patch.object(w, 'capture', side_effect=[w.ExportError('error:too-many-daily-captures'), f'https://web.archive.org/web/{stamp}/{SITE}/c.jpg']) as capture, patch.object(w.time, 'sleep'), patch.object(w, 'EXPORT_DIR', self.dist):
            self.assertEqual(w.main(), 1)
        self.assertEqual([call.args[2] for call in capture.call_args_list], urls[1:])
        new = [file for file in self.dist.glob('*.txt') if file.name != 'vojtamaur-web-wayback-previous.txt'][0]
        self.assertEqual(new.read_text().splitlines()[0], old)
        failure = json.loads(next(self.dist.glob('*.failures.jsonl')).read_text())
        self.assertEqual(failure['url'], urls[1])

    def test_simple_modes_defaults_custom_selection_and_pages_first(self):
        self.fixture()
        # Replace the deliberate broken child used by the parser tests.
        self.write('broken.xml', '<urlset/>')
        for options, count in [([], 2), (['--pages-only'], 2), (['--with-files'], 5), (['--types', 'images'], 1)]:
            with patch.object(sys, 'argv', ['export', '--dry-run', '--dist', str(self.dist)] + options), contextlib.redirect_stdout(io.StringIO()) as output, patch.object(w, 'capture', side_effect=AssertionError('must not capture')):
                self.assertEqual(w.main(), 0)
                lines = output.getvalue().splitlines()
                self.assertEqual(len(lines), count)
                if count > 1:
                    self.assertTrue(all(w.url_type(url) == 'pages' for url in lines[:2]))
        with patch.object(sys, 'argv', ['export', '--pages-only', '--with-files']), self.assertRaises(SystemExit):
            w.main()

    def test_authentication_failure_stops_without_retries(self):
        for code in (401, 403):
            opener = Mock()
            opener.open.side_effect = HTTPError(w.SAVE_URL, code, 'denied', {}, None)
            with self.assertRaises(w.AuthenticationFailed):
                w.capture(opener, 'SECRET', SITE + '/')
            self.assertEqual(opener.open.call_count, 1)

    def test_interrupt_during_cooldown_preserves_successes(self):
        urls = [SITE + '/a', SITE + '/b']
        snapshot = 'https://web.archive.org/web/20260928123456/' + urls[0]
        with patch.object(sys, 'argv', ['export']), patch.dict(w.os.environ, {'IA_ACCESS_KEY_ID': 'key', 'IA_SECRET_ACCESS_KEY': 'secret'}), patch.object(w, 'collect_urls', return_value=(urls, 0)), patch.object(w, 'capture', side_effect=[snapshot, KeyboardInterrupt]), patch.object(w.time, 'sleep'), patch.object(w, 'EXPORT_DIR', self.dist):
            self.assertEqual(w.main(), 130)
        self.assertEqual(next(self.dist.glob('*.txt')).read_text().strip(), snapshot)

    def test_retry_after_http_date(self):
        from email.utils import format_datetime
        future = datetime.now(timezone.utc) + timedelta(seconds=650)
        delay = w.backoff(0, format_datetime(future, usegmt=True))
        self.assertTrue(648 <= delay <= 650)


if __name__ == '__main__':
    unittest.main()
