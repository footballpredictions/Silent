import importlib.util
from pathlib import Path
import plistlib
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('release_bundle', Path(__file__).with_name('verify-release-bundle.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReleaseBundleTest(unittest.TestCase):
    def test_rejects_stale_app_extension_and_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            app = Path(directory) / 'Silent.app'
            tunnel = app / 'PlugIns/SilentTunnel.appex'
            revision = 'a' * 40
            for target in (app, tunnel):
                target.mkdir(parents=True, exist_ok=True)
                (target / 'Info.plist').write_bytes(plistlib.dumps({
                    'CFBundleVersion': '31', 'SilentBuildRevision': revision, 'CFBundleExecutable': 'Binary',
                }))
                (target / 'Binary').write_bytes(('(Запуск воркеров )[0-9]+[–-][0-9]+ ' + revision + ' TURN: канал не отвечает на повторную проверку TURN: нет ответа на две проверки').encode())
            module.verify(app, '31', revision)
            (tunnel / 'Binary').write_bytes((revision + ' TURN: канал не отвечает на повторную проверку TURN: нет ответа на две проверки').encode())
            module.verify(app, '31', revision)
            current_app = (app / 'Binary').read_bytes()
            (app / 'Binary').write_bytes(b'old app without current grouping')
            with self.assertRaises(ValueError): module.verify(app, '31', revision)
            (app / 'Binary').write_bytes(current_app)
            with self.assertRaises(ValueError): module.verify(app, '30', revision)
            with self.assertRaises(ValueError): module.verify(app, '31', 'b' * 40)
            original = (tunnel / 'Binary').read_bytes()
            (tunnel / 'Binary').write_bytes(b'resources old engine')
            with self.assertRaises(ValueError): module.verify(app, '31', revision)
            (tunnel / 'Binary').write_bytes(original + 'соединение с ретранслятором прервалось'.encode())
            with self.assertRaises(ValueError): module.verify(app, '31', revision)


if __name__ == '__main__': unittest.main()
