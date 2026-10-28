"""Run one explicit project script/module without discarding venv site-packages."""

import argparse
from pathlib import Path
import runpy
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument('--script')
    target.add_argument('--module-name')
    parser.add_argument('--project-path', action='append', default=[])
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    paths = []
    for value in args.project_path:
        path = Path(value)
        if not path.is_absolute() or not path.is_dir():
            raise ValueError('project paths must be existing absolute directories')
        paths.append(str(path.resolve()))
    sys.path[0:0] = list(dict.fromkeys(paths))
    arguments = args.arguments[1:] if args.arguments[:1] == ['--'] else args.arguments
    if args.script:
        script = Path(args.script)
        if not script.is_absolute() or not script.is_file():
            raise ValueError('script must be an existing absolute file')
        sys.argv = [str(script), *arguments]
        runpy.run_path(str(script), run_name='__main__')
    else:
        sys.argv = [args.module_name, *arguments]
        runpy.run_module(args.module_name, run_name='__main__', alter_sys=True)


if __name__ == '__main__':
    main()
