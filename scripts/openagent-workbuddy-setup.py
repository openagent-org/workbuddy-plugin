#!/usr/bin/env python3
"""合并 WorkBuddy 设置，调用原生插件管理并核验就绪；失败时停止，不安排重启。"""

import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', choices=('gitee', 'github'), help='新安装默认 gitee；已有官方来源在未指定时保留')
modes = parser.add_mutually_exclusive_group()
modes.add_argument('--check-config', action='store_true', help='只读预检配置，不等待插件下载')
modes.add_argument('--verify-only', action='store_true', help='只读核验配置及插件；不调用宿主管理命令')
modes.add_argument('--sync-only', action='store_true', help='要求配置已就绪，调用宿主同步并核验插件')
official_sources = {
    'gitee': {'source': 'git', 'url': 'https://gitee.com/openagent-org/workbuddy-plugin.git', 'ref': 'rel'},
    'github': {'source': 'git', 'url': 'https://github.com/openagent-org/workbuddy-plugin.git', 'ref': 'rel'},
}
args = parser.parse_args()
requested_source = args.source
selected_source = official_sources[requested_source or 'gitee']

# settings
import json, os, tempfile
from pathlib import Path

def write_if_changed(path, data, before, mode):
    if before is not None and data == json.loads(before):
        return False
    if args.check_config or args.verify_only or args.sync_only:
        raise SystemExit('CONFIG_UPDATE_REQUIRED=' + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.openagent-', dir=path.parent) as directory:
        temporary = Path(directory) / path.name
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.chmod(mode)
        if path.is_symlink() or (path.read_bytes() if path.exists() else None) != before:
            raise SystemExit('配置已被其他进程修改，停止并重新检查')
        os.replace(temporary, path)
    return True

path = Path.home() / '.workbuddy' / 'settings.json'
try:
    if path.is_symlink(): raise SystemExit('配置文件是符号链接，停止')
    before = path.read_bytes() if path.exists() else None
    data = json.loads(before) if before is not None else {}
    source = selected_source
    market = data.setdefault('extraKnownMarketplaces', {}).setdefault('openagent-workbuddy', {'source': source})
    if market.get('source') not in official_sources.values(): raise SystemExit('openagent-workbuddy 市场来源冲突，停止')
    if requested_source is None:
        source = market['source']
    selected_source = source
    market['source'] = source
    data.setdefault('enabledPlugins', {})['openagent@openagent-workbuddy'] = True
    mode = path.stat().st_mode & 0o777 if before is not None else 0o600

    if os.name == 'nt':
        local_changed = False
    else:
        project = Path(os.environ['CODEBUDDY_PROJECT_DIR']) if os.environ.get('CODEBUDDY_PROJECT_DIR') else Path.cwd()
        if not project.is_absolute() or not project.is_dir(): raise SystemExit('当前项目目录无效，停止')
        project_dir = project / '.codebuddy'
        local = project_dir / 'settings.local.json'
        if project_dir.is_symlink() or local.is_symlink(): raise SystemExit('项目配置目录或文件是符号链接，停止')
        local_before = local.read_bytes() if local.exists() else None
        local_data = json.loads(local_before) if local_before is not None else {}
        if not isinstance(local_data, dict): raise SystemExit('项目设置格式错误，停止')
        sandbox = local_data.setdefault('sandbox', {})
        if not isinstance(sandbox, dict): raise SystemExit('项目沙箱设置格式错误，停止')
        excluded = sandbox.setdefault('excludedCommands', [])
        if not isinstance(excluded, list) or any(not isinstance(item, str) for item in excluded):
            raise SystemExit('项目排除命令格式错误，停止')
        if 'openagent-workbuddy-restart.sh' not in excluded:
            excluded.append('openagent-workbuddy-restart.sh')
        local_mode = local.stat().st_mode & 0o777 if local_before is not None else 0o600

        local_changed = write_if_changed(local, local_data, local_before, local_mode)
    changed = write_if_changed(path, data, before, mode)
    print('CONFIG_WRITTEN' if changed or local_changed else 'CONFIG_UNCHANGED')
except (OSError, ValueError, TypeError, AttributeError):
    raise SystemExit('配置格式、字段类型或文件读写异常，停止') from None
if args.check_config:
    print('CONFIG_READY')
    raise SystemExit(0)
# plugin_verify
import gzip, hashlib, json, re, time, zlib
import shutil, subprocess
from pathlib import Path
root = Path.home() / '.workbuddy'
plugin = 'openagent@openagent-workbuddy'
base = (root / 'plugins/cache/openagent-workbuddy/openagent').resolve()
required = ['skills/openagent-' + name + '/SKILL.md' for name in 'first-task-router guide-agent search-agent run-agent query-account'.split()]
required.append('skills/openagent-first-task-router/references/plan-agent-discovery.md')
required.append('skills/openagent-first-task-router/references/result-validation-and-delivery.md')
required.append('skills/openagent-login/runtime-sign-in.md')
required.extend('skills/openagent-run-agent/scripts/' + name for name in ('cos_upload.cjs', 'cos_sdk.lock.json', 'cos_sdk.cjs.gz'))
def marketplace_matches(known, urls):
    """同步前允许两个官方源，完成后必须匹配本次所选源；共用登记格式校验。"""
    source = known.get('source', {})
    url = source.get('url', source.get('path'))
    return (source.get('source', known.get('type')) == 'git'
            and source.get('repo') in (None, '') and url in urls
            and source.get('path', url) == url and source.get('ref', 'rel') == 'rel')

def official_plugin_ready(record, cache):
    # 只改 settings 不代表宿主已迁移；旧源登记或旧版缓存不能作为完成证据。
    try:
        known = json.loads((root / 'plugins/known_marketplaces.json').read_bytes()).get('openagent-workbuddy', {})
        if not marketplace_matches(known, (selected_source['url'],)):
            return False
        version = record.get('version')
        if not isinstance(version, str) or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version):
            return False
        # 0.2.84 是首个支持两官方镜像的版本；旧缓存不能证明本次更新完成。
        if tuple(map(int, version.split('.'))) < (0, 2, 84):
            return False
        manifest = json.loads((cache / '.workbuddy-plugin/plugin.json').read_bytes())
        return manifest.get('name') == 'openagent' and manifest.get('version') == version
    except (OSError, ValueError, TypeError, AttributeError):
        return False

def bundle_ready(cache):
    try:
        scripts = cache / 'skills/openagent-run-agent/scripts'
        lock = json.loads((scripts / 'cos_sdk.lock.json').read_bytes())
        if not isinstance(lock, dict):
            return False
        packed = lock.get('bundle')
        if (lock.get('format') != 'openagent-cos-node-sdk-v1' or lock.get('minimum_node') != 20
                or not isinstance(lock.get('sdk'), dict) or lock['sdk'].get('name') != 'cos-nodejs-sdk-v5'
                or not isinstance(packed, dict) or packed.get('file') != 'cos_sdk.cjs.gz'):
            return False
        if any(not isinstance(packed.get(key), str) or not re.fullmatch(r'[a-f0-9]{64}', packed[key])
               for key in ('sha256', 'uncompressed_sha256')):
            return False
        if any(type(packed.get(key)) is not int or packed[key] <= 0 for key in ('size', 'uncompressed_size')):
            return False
        path = scripts / packed['file']
        if path.resolve() != path or not path.is_file():
            return False
        data = path.read_bytes()
        if len(data) != packed['size'] or hashlib.sha256(data).hexdigest() != packed['sha256']:
            return False
        unpacked = gzip.decompress(data)
        return (len(unpacked) == packed['uncompressed_size']
                and hashlib.sha256(unpacked).hexdigest() == packed['uncompressed_sha256'])
    except (OSError, ValueError, TypeError, EOFError, zlib.error):
        return False


def native_cli():
    """优先使用当前宿主的内置 CLI，兼容 PATH 中已有的命令入口。"""
    resources = os.environ.get('WORKBUDDY_RESOURCES_PATH')
    roots = [Path(resources)] if resources else []
    if os.name == 'nt' and not resources:
        try:
            process = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false); "
                "Get-Process WorkBuddy -ErrorAction Stop | Select-Object -ExpandProperty Path -Unique"],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=5, check=True)
        except (OSError, subprocess.SubprocessError):
            raise SystemExit('无法定位运行中的 WorkBuddy；插件未同步，未安排重启') from None
        paths = process.stdout.strip().splitlines()
        if len(paths) != 1 or not Path(paths[0]).is_absolute():
            raise SystemExit('WorkBuddy 程序路径不唯一或无效；停止同步')
        roots.append(Path(paths[0]).parent / 'resources')
    for directory in (Path('/Applications'), Path.home() / 'Applications'):
        for name in ('WorkBuddy.app', 'WorkBuddy AI.app'):
            roots.append(directory / name / 'Contents/Resources')
    for directory in roots:
        entry = directory / 'app.asar.unpacked/cli/bin/codebuddy'
        if entry.is_file():
            versions = root / 'binaries/node/versions'
            pattern = '*/node.exe' if os.name == 'nt' else '*/bin/node'
            nodes = [path for path in versions.glob(pattern) if path.is_file()]
            nodes.sort(key=lambda path: tuple(map(int, re.findall(r'\d+', path.relative_to(versions).parts[0]))))
            node = str(nodes[-1]) if nodes else shutil.which('node')
            if not node:
                raise SystemExit('未找到宿主 Node.js，无法调用 WorkBuddy 插件管理；未安排重启')
            return [node, str(entry)]
    command = shutil.which('codebuddy')
    if command:
        return [command]
    raise SystemExit('未找到 WorkBuddy 内置或 PATH 中的 codebuddy CLI；插件未同步，未安排重启')


def sync_plugins(deadline):
    """显式管理固定的官方市场和用户级插件；宿主负责下载、并发锁及登记。"""
    registry = root / 'plugins/known_marketplaces.json'
    try:
        known = json.loads(registry.read_bytes()).get('openagent-workbuddy') if registry.exists() else None
        if known and not marketplace_matches(known, tuple(item['url'] for item in official_sources.values())):
            raise SystemExit('宿主已登记的 openagent-workbuddy 来源冲突；停止同步')
    except (OSError, ValueError, TypeError, AttributeError):
        raise SystemExit('宿主市场登记无法读取；停止同步') from None
    command = native_cli()
    environment = dict(os.environ, WORKBUDDY_CONFIG_DIR=str(root), CODEBUDDY_CONFIG_DIR=str(root),
                       CODEBUDDY_PLUGIN_BACKGROUND_MANAGEMENT='0', CODEBUDDY_SKIP_BUILTIN_MARKETPLACE='1')
    entry = Path(command[-1]).resolve()
    dist = entry.parent.parent / 'dist'
    if (dist / 'codebuddy-lite-wb.mjs').is_file() and not (dist / 'codebuddy.js').is_file():
        environment['CODEBUDDY_FORCE_LITE_WB_BUNDLE'] = '1'
    # 宿主 marketplace add 不接受 ref；先确认官方仓库的默认分支仍为 rel。
    steps = (
        ('发布分支核验', ['git', 'ls-remote', '--symref', selected_source['url'], 'HEAD']),
        ('市场同步', [*command, 'plugin', 'marketplace', 'add', selected_source['url'], '--name', 'openagent-workbuddy']),
        ('插件安装', [*command, 'plugin', 'install', plugin, '--scope', 'user']),
    )
    for name, arguments in steps:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SystemExit('插件同步等待超时，状态未确认；未安排重启，请先检查宿主安装状态')
        try:
            result = subprocess.run(arguments, cwd=root.parent, env=environment, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=remaining)
        except (OSError, subprocess.SubprocessError):
            raise SystemExit(name + '异常或超时，状态未确认；未安排重启，请先检查宿主安装状态') from None
        output = result.stdout + '\n' + result.stderr
        # CLI 某些错误仍返回 0；原始输出可能含本机配置，不直接回显。
        if result.returncode or re.search(r'Failed to (?:add marketplace|install plugin\(s\)):', output):
            raise SystemExit(name + '失败；未安排重启，请检查 WorkBuddy 插件管理日志')
        if name == '发布分支核验' and 'ref: refs/heads/rel\tHEAD' not in result.stdout.splitlines():
            raise SystemExit('官方插件仓库默认分支不是 rel；停止同步')
    print('PLUGIN_SYNCED')


deadline = time.monotonic() + 60
if not args.verify_only:
    sync_plugins(deadline)
try:
    while True:
        settings = json.loads((root / 'settings.json').read_bytes())
        source = selected_source
        if settings.get('enabledPlugins', {}).get(plugin) is not True or settings.get('extraKnownMarketplaces', {}).get('openagent-workbuddy', {}).get('source') != source:
            raise SystemExit('插件未启用或市场来源不符，停止')
        try:
            records = json.loads((root / 'plugins/installed_plugins.json').read_bytes()).get('plugins', {}).get(plugin, [])
        except FileNotFoundError:
            records = []
        ready = False
        for record in records:
            if record.get('scope') != 'user': continue
            cache = Path(record['installPath']).resolve()
            if not cache.is_relative_to(base): raise SystemExit('插件登记路径异常，停止')
            if (official_plugin_ready(record, cache)
                    and all(p.is_file() and p.stat().st_size > 0 for p in map(cache.joinpath, required))
                    and bundle_ready(cache)):
                ready = True
                break
        if ready:
            print('PLUGIN_READY')
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0: raise SystemExit('所选官方插件来源或下载尚未确认，等待超时；请检查插件页是否已刷新所选源、Git 和网络，不自动重新执行合并命令')
        time.sleep(min(1, remaining))
except (OSError, ValueError, TypeError, AttributeError, KeyError):
    raise SystemExit('插件下载尚未确认，安装登记或文件无法读取') from None
