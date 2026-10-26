"""Reassemble staged APK assets; publish only after checking the complete download."""
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

REPO = 'DevMehd/NuvioPersoReleases'


def validate(repo, release_id, name, digest, parts):
    if repo != REPO or not re.fullmatch(r'[1-9][0-9]*', release_id):
        raise ValueError('Unexpected repository or release ID')
    match = re.fullmatch(r'nuvio-perso-(\d+\.\d+\.\d+(?:-beta\.\d+)?)\.apk', name)
    if not match or not re.fullmatch(r'[a-f0-9]{64}', digest) or not parts.isdecimal() or not 1 <= int(parts) <= 32:
        raise ValueError('Invalid artifact name, digest or part count')
    return 'v' + match[1]


def api(path, method='GET', **fields):
    args = ['gh', 'api', f'repos/{REPO}/{path}', '--method', method]
    for key, value in fields.items():
        args += ['-F', f'{key}={str(value).lower() if isinstance(value, bool) else value}']
    data = subprocess.check_output(args)
    return json.loads(data) if data else None


def download(asset, target):
    with target.open('wb') as output:
        subprocess.run(['gh', 'api', f'repos/{REPO}/releases/assets/{int(asset["id"])}', '-H', 'Accept: application/octet-stream'], stdout=output, check=True, timeout=240)


def upload(tag, apk):
    subprocess.run(['gh', 'release', 'upload', tag, str(apk), '--repo', REPO], check=True, timeout=300)


def verify(path, digest):
    with path.open('rb') as source:
        actual = hashlib.file_digest(source, 'sha256').hexdigest()
    if actual != digest:
        raise ValueError('Complete APK checksum mismatch')


def publish(release_id, name, digest, parts, folder):
    tag = validate(REPO, release_id, name, digest, str(parts))
    release = api(f'releases/{release_id}')
    if release['tag_name'] != tag or not release['draft']:
        raise ValueError('Release must be the matching draft')
    assets = {a['name']: a for a in release['assets']}
    chunk_names = [f'{name}.part-{i:03}' for i in range(parts)]
    apk = folder / name
    if name not in assets:
        with apk.open('wb') as output:
            for chunk_name in chunk_names:
                chunk = assets.get(chunk_name)
                if not chunk or chunk['state'] != 'uploaded':
                    raise ValueError('Missing staged part: ' + chunk_name)
                part = folder / 'part'
                download(chunk, part)
                with part.open('rb') as source:
                    while block := source.read(1024 * 1024): output.write(block)
                part.unlink()
        verify(apk, digest)
        upload(tag, apk)
        assets = {a['name']: a for a in api(f'releases/{release_id}')['assets']}
    final = assets[name]
    if final['state'] != 'uploaded' or final.get('digest') != 'sha256:' + digest:
        raise ValueError('Unexpected final asset; refusing to overwrite it')
    download(final, apk)
    verify(apk, digest)
    if apk.stat().st_size != final['size']:
        raise ValueError('Final asset size mismatch')
    for chunk_name in chunk_names:
        if chunk_name in assets:
            api(f'releases/assets/{int(assets[chunk_name]["id"])}', method='DELETE')
    api(f'releases/{release_id}', method='PATCH', draft=False)
    print(f'Published {tag}: {name}, sha256 {digest}')


if __name__ == '__main__':
    fields = [os.environ[key] for key in ['GITHUB_REPOSITORY', 'RELEASE_ID', 'APK_NAME', 'APK_SHA256', 'APK_PARTS']]
    validate(*fields)
    with tempfile.TemporaryDirectory(prefix='nuvio-apk-') as folder:
        publish(fields[1], fields[2], fields[3], int(fields[4]), Path(folder))
