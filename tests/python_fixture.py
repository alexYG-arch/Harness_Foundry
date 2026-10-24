"""Test-only executable headers preserving the selected Python and its venv."""

import shlex
import sys


def python_fixture_header(interpreter=None):
    # A kernel shebang cannot quote spaces. sh exec preserves argv and the PID;
    # Python treats the trampoline as a module docstring. Never resolve a venv link.
    executable = sys.executable if interpreter is None else str(interpreter)
    return "#!/bin/sh\n" + "'''exec' " + shlex.quote(executable) + ' "$0" "$@"\n' + "' '''\n"
