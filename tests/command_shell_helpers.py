"""Python fixtures executed through the product's native shell path."""
import base64
import os
import shlex
import subprocess
import sys


def python_shell_command(code, executable=None):
    """Keep source quotes, newlines and shell metacharacters out of shell syntax."""
    payload = base64.b64encode(code.encode('utf-8')).decode('ascii')
    bootstrap = "import base64;exec(base64.b64decode('%s'))" % payload
    argv = [executable or sys.executable, '-c', bootstrap]
    if os.name == 'nt':
        # The bootstrap has no embedded double quotes or cmd expansions.
        return subprocess.list2cmdline(argv)
    return shlex.join(argv)
