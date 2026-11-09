#!/usr/bin/env python3
"""Install or remove a per-user macOS launch agent for the local Shiji server."""
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys


LABEL = 'com.shiji.opensource'
ACCOUNT_TEST_LABEL = 'com.shiji.account-test'
ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path.home() / 'Library' / 'Application Support' / 'Shiji'
AGENT = Path.home() / 'Library' / 'LaunchAgents' / f'{LABEL}.plist'
TARGET = f'gui/{os.getuid()}/{LABEL}'


def run(*args, check=True):
    return subprocess.run(['launchctl', *args], check=check, capture_output=True, text=True)


def install(demo=False, account_test_profile=''):
    account_test = bool(account_test_profile)
    label = ACCOUNT_TEST_LABEL if account_test else LABEL
    agent = Path.home() / 'Library' / 'LaunchAgents' / f'{label}.plist'
    target = f'gui/{os.getuid()}/{label}'
    port = 8880 if account_test else 8879
    previous_cloud_origin = ''
    if agent.is_file():
        try:
            previous_cloud_origin = plistlib.loads(agent.read_bytes()).get('EnvironmentVariables', {}).get('SHIJI_CLOUD_ORIGIN', '')
        except (OSError, ValueError, TypeError):
            pass
    cloud_origin = '' if account_test else os.environ.get('SHIJI_CLOUD_ORIGIN', previous_cloud_origin)
    run('bootout', target, check=False)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    data_dir = RUNTIME / ('account-test-data' if account_test else 'demo-data' if demo else 'data')
    data_dir.mkdir(exist_ok=True)
    shutil.copytree(ROOT / 'shiji', RUNTIME / 'shiji', dirs_exist_ok=True)
    if not (RUNTIME / '.venv' / 'bin' / 'python').is_file():
        shutil.copytree(ROOT / '.venv', RUNTIME / '.venv', symlinks=True)
    shutil.copy2(ROOT / 'run.sh', RUNTIME / 'run.sh')
    agent.parent.mkdir(parents=True, exist_ok=True)
    log = data_dir / 'server.log'
    path = f'{Path.home() / ".local/bin"}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'
    config = {
        'Label': label,
        'ProgramArguments': [str(RUNTIME / 'run.sh')],
        'WorkingDirectory': str(RUNTIME),
        'EnvironmentVariables': {'PATH': path, 'HOME': str(Path.home()),
                                 'SHIJI_DATA_DIR': str(data_dir),
                                 'SHIJI_DEMO_MODE': '1' if demo else '0',
                                 'SHIJI_PORT': str(port),
                                 'SHIJI_CLOUD_ORIGIN': cloud_origin,
                                 'SHIJI_EXCLUDE_PROFILE_ID': account_test_profile,
                                 'SHIJI_PREVIOUS_ACCOUNT_URL': os.environ.get('SHIJI_PREVIOUS_ACCOUNT_URL', '') if account_test else ''},
        'RunAtLoad': True,
        'KeepAlive': True,
        'StandardOutPath': str(log),
        'StandardErrorPath': str(log),
    }
    agent.write_bytes(plistlib.dumps(config))
    agent.chmod(0o644)
    result = run('bootstrap', f'gui/{os.getuid()}', str(agent), check=False)
    if result.returncode:
        raise SystemExit(result.stderr.strip() or 'launchctl bootstrap failed')
    print(f'已启动登录项：{label} {"(模拟测试)" if demo else "(新账号测试)" if account_test else ""}\nhttp://127.0.0.1:{port}/import')


def uninstall(account_test=False):
    label = ACCOUNT_TEST_LABEL if account_test else LABEL
    run('bootout', f'gui/{os.getuid()}/{label}', check=False)
    (Path.home() / 'Library' / 'LaunchAgents' / f'{label}.plist').unlink(missing_ok=True)
    print(f'已移除登录项：{label}')


if __name__ == '__main__':
    command = sys.argv[1] if len(sys.argv) > 1 else ''
    if sys.platform != 'darwin' or command not in ('install', 'install-demo', 'install-account-test', 'uninstall', 'uninstall-account-test'):
        raise SystemExit('用法：python scripts/service.py install|install-demo|install-account-test PROFILE_ID|uninstall|uninstall-account-test')
    if command == 'install-account-test':
        if len(sys.argv) != 3 or not re.fullmatch(r'[0-9a-f]{24}', sys.argv[2], re.I):
            raise SystemExit('安装新账号测试服务时需要当前账号的完整主页 ID')
        install(account_test_profile=sys.argv[2].lower())
    elif len(sys.argv) != 2:
        raise SystemExit('参数数量无效')
    elif command.startswith('uninstall'):
        uninstall(account_test=command == 'uninstall-account-test')
    else:
        install(demo=command == 'install-demo')
