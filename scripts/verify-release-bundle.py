"""Verify the exact exported app, extension and native engine before upload."""
import hashlib
import json
import plistlib
from pathlib import Path
import sys


def verify(app, build, revision):
    result = {}
    for name, directory in [('app', app), ('tunnel', app / 'PlugIns/SilentTunnel.appex')]:
        metadata = plistlib.loads((directory / 'Info.plist').read_bytes())
        if str(metadata.get('CFBundleVersion')) != str(build):
            raise ValueError(f'{name}: wrong build number')
        if metadata.get('SilentBuildRevision') != revision:
            raise ValueError(f'{name}: wrong source revision')
        binary = (directory / metadata['CFBundleExecutable']).read_bytes()
        if name == 'tunnel':
            for marker in [revision, 'TURN: канал не отвечает на повторную проверку', 'TURN: нет ответа на две проверки',
                           'TURN: разрешение и канал продлены после сна',
                           'DTLS: срок простоя канала истёк, новое рукопожатие']:
                if marker.encode() not in binary:
                    raise ValueError('tunnel: native engine does not match the release')
            if 'соединение с ретранслятором прервалось'.encode() in binary:
                raise ValueError('tunnel: obsolete native journal found')
        # Only the app renders grouped rows. The extension merely writes raw
        # events, so its optimizer correctly strips the unused grouping code.
        if name == 'app' and '(Запуск воркеров )[0-9]+[–-][0-9]+'.encode() not in binary:
            raise ValueError(f'{name}: current journal grouping is missing')
        result[name] = hashlib.sha256(binary).hexdigest()
    return {'build': str(build), 'revision': revision, 'sha256': result}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1]), sys.argv[2], sys.argv[3])))
