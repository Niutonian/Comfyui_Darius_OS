"""Download public Kokoro release assets into Darius, never the user home/cache."""
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'data' / 'models' / 'pipecat'


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    headers = {'User-Agent': 'Darius-Pipecat-Setup'}
    request = urllib.request.Request('https://api.github.com/repos/thewh1teagle/kokoro-onnx/releases/tags/model-files-v1.0', headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        assets = {item['name']: item for item in json.load(response)['assets']}
    records = {}
    for name in ('kokoro-v1.0.onnx', 'voices-v1.0.bin'):
        info, target = assets[name], DEST / name
        expected = (info.get('digest') or '').removeprefix('sha256:')
        if not target.exists() or target.stat().st_size != info['size']:
            temporary = target.with_suffix(target.suffix + '.part')
            print('Downloading', name, f"({info['size'] // 1024 // 1024} MiB)", flush=True)
            with urllib.request.urlopen(urllib.request.Request(info['browser_download_url'], headers=headers), timeout=120) as response, temporary.open('wb') as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
            if temporary.stat().st_size != info['size']:
                raise ValueError('Incomplete download: ' + name)
            with temporary.open('rb') as stream:
                checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
            if expected and checksum != expected:
                raise ValueError('Checksum mismatch: ' + name)
            temporary.replace(target)
        with target.open('rb') as stream:
            checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
        if expected and checksum != expected:
            raise ValueError('Existing model checksum mismatch: ' + name)
        records[name] = {'sha256': checksum, 'bytes': target.stat().st_size, 'source': info['browser_download_url']}
    (DEST / 'manifest.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
    print('Pipecat CPU models ready.', flush=True)


if __name__ == '__main__':
    main()
