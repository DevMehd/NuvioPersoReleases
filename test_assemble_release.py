import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import assemble_release as release

REPO = 'DevMehd/NuvioPersoReleases'
NAME = 'nuvio-perso-2.0.0-beta.48.apk'
PAYLOAD = b'verified apk bytes'
SHA = hashlib.sha256(PAYLOAD).hexdigest()

class ReleaseTests(unittest.TestCase):
    def test_rejects_untrusted_inputs(self):
        valid = [REPO, '424655121', NAME, SHA, '2']
        for index, bad in [(0, 'other/repo'), (1, '../1'), (2, '../bad.apk'), (3, 'bad'), (4, '0'), (4, '33')]:
            args = valid.copy(); args[index] = bad
            with self.subTest(index=index, bad=bad), self.assertRaises(ValueError):
                release.validate(*args)

    def run_release(self, payload=PAYLOAD, existing=False, draft=True):
        assets = [{'id': 1, 'name': NAME + '.part-000', 'state': 'uploaded'},
                  {'id': 2, 'name': NAME + '.part-001', 'state': 'uploaded'}]
        final = {'id': 3, 'name': NAME, 'state': 'uploaded', 'digest': 'sha256:' + SHA, 'size': len(PAYLOAD)}
        if existing: assets.append(final)
        data = {'tag_name': 'v2.0.0-beta.48', 'draft': draft, 'assets': assets}
        calls = []
        def api(path, method='GET', **fields):
            calls.append((path, method, fields))
            return data
        def download(asset, target):
            target.write_bytes(payload[:5] if asset['id'] == 1 else payload[5:] if asset['id'] == 2 else PAYLOAD)
        def upload(*args):
            data['assets'].append(final)
        with tempfile.TemporaryDirectory() as folder, patch.object(release, 'api', side_effect=api), patch.object(release, 'download', side_effect=download), patch.object(release, 'upload', side_effect=upload):
            release.publish('424655121', NAME, SHA, 2, Path(folder))
        return calls

    def test_wrong_assembled_digest_never_deletes_or_publishes(self):
        with patch.object(release, 'api') as api:
            api.return_value = {'tag_name': 'v2.0.0-beta.48', 'draft': True, 'assets': [
                {'id': 1, 'name': NAME + '.part-000', 'state': 'uploaded'},
                {'id': 2, 'name': NAME + '.part-001', 'state': 'uploaded'}]}
            with tempfile.TemporaryDirectory() as folder, patch.object(release, 'download', side_effect=lambda a,p: p.write_bytes(b'corrupt')), patch.object(release, 'upload') as upload:
                with self.assertRaises(ValueError): release.publish('424655121', NAME, SHA, 2, Path(folder))
                upload.assert_not_called()
                self.assertTrue(all(c.kwargs.get('method', 'GET') == 'GET' for c in api.call_args_list))

    def test_verified_file_publishes_after_chunk_cleanup(self):
        calls = self.run_release()
        mutations = [(path, method) for path,method,_ in calls if method != 'GET']
        self.assertEqual(mutations, [('releases/assets/1', 'DELETE'), ('releases/assets/2', 'DELETE'), ('releases/424655121', 'PATCH')])
        self.assertEqual(calls[-1][2], {'draft': False})

    def test_verified_existing_file_can_resume(self):
        self.assertEqual(self.run_release(existing=True)[-1][1], 'PATCH')

    def test_public_release_is_not_modified(self):
        with self.assertRaises(ValueError): self.run_release(draft=False)

if __name__ == '__main__': unittest.main()
