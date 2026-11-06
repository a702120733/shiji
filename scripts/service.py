#!/usr/bin/env python3
"""Install or remove a per-user macOS launch agent for the local Shiji server."""
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys


LABEL = 'com.shiji.opensource'
ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path.home() / 'Library' / 'Application Support' / 'Shiji'
AGENT = Path.home() / 'Library' / 'LaunchAgents' / f'{LABEL}.plist'
TARGET = f'gui/{os.getuid()}/{LABEL}'


def run(*args, check=True):
    return subprocess.run(['launchctl', *args], check=check, capture_output=True, text=True)


def install():
    run('bootout', TARGET, check=False)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (RUNTIME / 'data').mkdir(exist_ok=True)
    shutil.copytree(ROOT / 'shiji', RUNTIME / 'shiji', dirs_exist_ok=True)
    if not (RUNTIME / '.venv' / 'bin' / 'python').is_file():
        shutil.copytree(ROOT / '.venv', RUNTIME / '.venv', symlinks=True)
    shutil.copy2(ROOT / 'run.sh', RUNTIME / 'run.sh')
    AGENT.parent.mkdir(parents=True, exist_ok=True)
    log = RUNTIME / 'data' / 'server.log'
    path = f'{Path.home() / ".local/bin"}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'
    config = {
        'Label': LABEL,
        'ProgramArguments': [str(RUNTIME / 'run.sh')],
        'WorkingDirectory': str(RUNTIME),
        'EnvironmentVariables': {'PATH': path, 'HOME': str(Path.home())},
        'RunAtLoad': True,
        'KeepAlive': True,
        'StandardOutPath': str(log),
        'StandardErrorPath': str(log),
    }
    AGENT.write_bytes(plistlib.dumps(config))
    AGENT.chmod(0o644)
    result = run('bootstrap', f'gui/{os.getuid()}', str(AGENT), check=False)
    if result.returncode:
        raise SystemExit(result.stderr.strip() or 'launchctl bootstrap failed')
    print(f'已启动登录项：{LABEL}\nhttp://127.0.0.1:8879/import')


def uninstall():
    run('bootout', TARGET, check=False)
    AGENT.unlink(missing_ok=True)
    print(f'已移除登录项：{LABEL}')


if __name__ == '__main__':
    if sys.platform != 'darwin' or len(sys.argv) != 2 or sys.argv[1] not in ('install', 'uninstall'):
        raise SystemExit('用法：python scripts/service.py install|uninstall（macOS）')
    (install if sys.argv[1] == 'install' else uninstall)()
