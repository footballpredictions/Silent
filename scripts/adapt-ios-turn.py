"""Keep a rejected TURN Refresh response from being reported as success on iOS."""
from pathlib import Path
import shutil
import stat
import sys


def patch(source):
    old = ('\t\t\treturn err\n\t\t}\n\n'
           '\t\treturn fmt.Errorf("%s", res.Type) //nolint:err113\n')
    new = ('\t\t\treturn fmt.Errorf("TURN refresh rejected (%d)", code.Code)\n\t\t}\n\n'
           '\t\treturn fmt.Errorf("%s", res.Type) //nolint:err113\n')
    if source.count(old) != 1:
        raise ValueError("Pion TURN Refresh handling changed; review the iOS patch")
    return source.replace(old, new, 1)


def prepare(source, target, unpatched=False):
    if not (source / 'internal/client/allocation.go').is_file():
        raise ValueError("Pion TURN module was not downloaded; refusing to copy an unrelated directory")
    shutil.copytree(source, target)
    path = target / 'internal/client/allocation.go'
    if not unpatched:
        path.chmod(path.stat().st_mode | stat.S_IWRITE)
        path.write_text(patch(path.read_text(encoding='utf-8')), encoding='utf-8')
    shutil.copyfile(Path(__file__).parent / 'fixtures/turn/refresh_test.go', target / 'internal/client/ios_refresh_test.go')


if __name__ == '__main__':
    prepare(Path(sys.argv[1]), Path(sys.argv[2]), unpatched='--unpatched' in sys.argv[3:])
