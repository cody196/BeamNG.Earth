"""Custom sign builds must not launch a staged stock release without their features."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'server'))
import launcher
import selfupdate
import updates
from tools import build_app, package


class CustomBuildUpdatesTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.bundle = self.folder / 'bundle'
        self.bundle.mkdir()
        self.marker = self.bundle / 'BUILD_VARIANT'
        self.marker.write_text('state-welcome-v4\n', encoding='utf-8')
        # The marker travels inside the EXE, independent of its filename.
        self.exe = self.folder / 'renamed.exe'
        self.exe.write_bytes(b'custom')
        self.stock = self.folder / 'BeamNG.Earth-1.9.1-beta.exe'
        self.stock.write_bytes(b'stock release without welcome signs')
        self.note = self.folder / selfupdate.STAGED
        self.note.write_text(json.dumps(dict(version='1.9.1-beta', path=self.stock.name,
                            sha256=hashlib.sha256(self.stock.read_bytes()).hexdigest())), encoding='utf-8')
        patch = mock.patch.object(updates, 'ROOT', str(self.bundle))
        patch.start()
        self.addCleanup(patch.stop)
        self.net = mock.Mock()
        self.net.get.return_value.body = json.dumps(dict(tag_name='v1.9.1-beta',
            html_url=updates.PAGE_URL + '/tag/v1.9.1-beta')).encode()

    def test_repeated_launch_ignores_stock_update_and_preserves_it(self):
        before = self.note.read_bytes()
        for _ in range(2):
            self.assertIsNone(selfupdate.staged('1.9.0-beta', str(self.exe)))
        self.assertEqual(self.note.read_bytes(), before)
        self.assertTrue(self.stock.is_file())

    def test_launcher_does_not_hand_over_to_stock(self):
        with mock.patch.object(launcher, 'FROZEN', True), \
             mock.patch.object(selfupdate, 'packaged_path', return_value=str(self.exe)), \
             mock.patch.object(launcher.subprocess, 'Popen') as popen:
            self.assertFalse(launcher.hand_over())
        popen.assert_not_called()

    def test_in_game_check_does_not_offer_incompatible_release(self):
        self.assertIsNone(updates.check('1.9.0-beta', self.net))
        self.net.get.assert_not_called()

    def test_startup_keeps_custom_build_without_an_update_prompt(self):
        popup = mock.Mock(return_value=False)
        with mock.patch('netfetch.default_fetcher', return_value=self.net):
            self.assertFalse(launcher.update_at_start(argparse.Namespace(no_update_check=False),
                                                     packaged=True, popup=popup))
        popup.assert_not_called()
        self.net.get.assert_not_called()

    def test_explicit_update_request_explains_custom_build_without_downloading(self):
        with mock.patch.object(selfupdate, '_get_json') as fetch:
            with self.assertRaisesRegex(selfupdate.UpdateError, 'custom build'):
                selfupdate.download(self.net, '1.9.0-beta', str(self.exe))
        fetch.assert_not_called()
        self.net.session.assert_not_called()

    def test_stock_builds_still_update(self):
        self.marker.unlink()
        self.assertEqual(selfupdate.staged('1.9.0-beta', str(self.exe)), str(self.stock))
        self.assertEqual(updates.check('1.9.0-beta', self.net)['latest'], '1.9.1-beta')

    def test_frozen_build_embeds_variant_and_stock_build_does_not(self):
        work = self.folder / 'work'
        work.mkdir()
        for variant in ('state-welcome-v4', None):
            with mock.patch.object(build_app.subprocess, 'run') as run:
                build_app.pyinstaller(str(work), 'icon.ico', True, ver='1.9.0-beta', build_variant=variant)
            cmd = run.call_args.args[0]
            markers = [cmd[i+1].split(build_app.SEP, 1)[0] for i, value in enumerate(cmd[:-1])
                       if value == '--add-data' and 'BUILD_VARIANT' in cmd[i+1]]
            self.assertEqual(len(markers), int(bool(variant)))
            if variant:
                self.assertEqual(Path(markers[0]).read_text().strip(), variant)

    def test_source_package_keeps_variant(self):
        import zipfile
        out = self.folder / 'packages'
        with mock.patch.object(sys, 'argv', ['package.py', '--out', str(out),
                                           '--build-variant', 'state-welcome-v4']), \
             mock.patch.object(package, 'collect', return_value=['VERSION']):
            package.main()
        ver = package.version()
        with zipfile.ZipFile(out / f'BeamNG.Earth-{ver}.zip') as z:
            self.assertEqual(z.read(f'BeamNG.Earth-{ver}/BUILD_VARIANT'), b'state-welcome-v4\n')


if __name__ == '__main__':
    unittest.main()
