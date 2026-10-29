"""Run the actual packaged shell MTU policy, including bootstrap isolation."""
import unittest
import test_path_runtime as runtime


@unittest.skipUnless(runtime.SHELL, 'POSIX shell required')
class ProfileMtuTests(unittest.TestCase):
    run_shell = runtime.RouterRuntimeTests.run_shell

    def test_metadata_validation_and_bootstrap(self):
        lines = self.run_shell(r'''
jsonfilter() { echo "$RECOMMENDED"; }
for RECOMMENDED in 1420 1200 1280 0 9000 bad ''; do
  sv_path_profile_mtu fixture
done
touch "$SV_RUN/bootstrap"
RECOMMENDED=1420
sv_path_profile_mtu fixture
''', library='path.sh')
        self.assertEqual(lines, ['1420', '1280', '1280', '1280', '1280', '1280', '1280', '1280'])


if __name__ == '__main__':
    unittest.main()
