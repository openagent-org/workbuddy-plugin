#!/usr/bin/env python3
"""合并 WorkBuddy 插件设置并只读等待下载就绪；失败时停止，不安排重启。"""

import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source', choices=('gitee', 'github'), help='新安装默认 gitee；已有官方来源在未指定时保留')
parser.add_argument('--verify-only', action='store_true', help='只读核验配置及插件；配置有差异时停止，不写入')
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
    if args.verify_only:
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
    legacy_source = {'source': 'git', 'url': 'https://oasn-ow.haimawan.com/git/openagent/workbuddy-plugin.git', 'ref': 'rel'}
    market = data.setdefault('extraKnownMarketplaces', {}).setdefault('openagent-workbuddy', {'source': source})
    if market.get('source') not in (*official_sources.values(), legacy_source): raise SystemExit('openagent-workbuddy 市场来源冲突，停止')
    if requested_source is None and market['source'] in official_sources.values():
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
# plugin_verify
import gzip, hashlib, json, re, time, zlib
from pathlib import Path
root = Path.home() / '.workbuddy'
plugin = 'openagent@openagent-workbuddy'
base = (root / 'plugins/cache/openagent-workbuddy/openagent').resolve()
required = ['skills/openagent-' + name + '/SKILL.md' for name in 'first-task-router guide-agent search-agent run-agent query-account'.split()]
required.append('skills/openagent-first-task-router/references/result-validation-and-delivery.md')
required.append('skills/openagent-login/runtime-sign-in.md')
required.extend('skills/openagent-run-agent/scripts/' + name for name in ('cos_upload.cjs', 'cos_sdk.lock.json', 'cos_sdk.cjs.gz'))
def official_plugin_ready(record, cache):
    # 只改 settings 不代表宿主已迁移；旧源登记或旧版缓存不能作为完成证据。
    try:
        known = json.loads((root / 'plugins/known_marketplaces.json').read_bytes()).get('openagent-workbuddy', {})
        source = known.get('source', {})
        url = selected_source['url']
        if (source.get('source', known.get('type')) != 'git'
                or source.get('repo') not in (None, '')
                or source.get('url', source.get('path')) != url
                or ('path' in source and source['path'] != url)
                or source.get('ref', 'rel') != 'rel'):
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

deadline = time.monotonic() + 60
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
