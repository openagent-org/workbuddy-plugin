#!/usr/bin/env python3
"""可独立下载的 WorkBuddy OpenAgent 卸载器；仅依赖 Python 3.9+ 标准库。"""

import copy
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile

OPENAGENT_ENDPOINTS = (
    "https://oasn-ow.haimawan.com/mcp/v1/open-agent",
    "https://oasn-pre.haimawan.com/mcp/v1/open-agent",
    "https://oasn-test.haimawan.com/e/preview/mcp/v1/open-agent",
    "https://oasn-pre.haimawan.com/e/hkpreview/mcp/v1/open-agent-workbuddy",
    "https://oasn-pre.haimawan.com/e/hkpreview/mcp/v1/open-agent",
)
OPENAGENT_SKILLS = (
    "user-guide", "use-agent", "stop-agent",
    "openagent-first-task-router", "openagent-guide-agent", "openagent-search-agent",
    "openagent-run-agent", "openagent-query-account",
)
PROFILES = (
    ("openagent", "openagent-oauth.json"),
    ("openagent-rel", "openagent-rel-oauth.json"),
)
OAUTH_FILE_ALIASES = (
    "openagent_oauth.json", "oasn-openagent-credentials.json",
    "openagent-client.json", ".openagent-oauth.json",
)
MARKETPLACE = "openagent-workbuddy"
PLUGIN_ID = "openagent@" + MARKETPLACE
MARKETPLACE_URL = "https://github.com/openagent-org/workbuddy-plugin.git"
MARKETPLACE_URLS = {
    MARKETPLACE_URL,
    "https://oasn-ow.haimawan.com/git/openagent/workbuddy-plugin.git",
}


def config_roots(home):
    """沿用宿主配置环境；无覆盖时按当前用户查找，并保留旧版清理。"""
    home = home.resolve(strict=True)
    override = (os.environ.get("WORKBUDDY_CONFIG_DIR", "").strip()
                or os.environ.get("CODEBUDDY_CONFIG_DIR", "").strip())
    primary = Path(override).expanduser() if override else home / ".workbuddy"
    roots = list(dict.fromkeys((primary, home / ".workbuddy", home / ".workbuddy-ai")))
    for root in roots:
        if not root.is_absolute() or ".." in root.parts or root in (home, Path(root.anchor)):
            raise ValueError("配置目录必须是明确的绝对目录，不能为用户主目录或文件系统根目录")
        # 不 resolve 掉符号链接，防止把跳转后的目录当成已授权边界。
        safe_stat(Path(root.anchor), root)
    return roots


def require_object(value, label):
    if not isinstance(value, dict):
        raise ValueError(label + " 必须是 JSON 对象")
    return value


def parse_json(source, label):
    """解析失败不携带原文，防止凭据进入错误输出。"""
    try:
        return require_object(json.loads(source), label)
    except (ValueError, UnicodeError):
        raise ValueError(label + " 不是合法 JSON 对象；未清理") from None


def is_managed_proxy_config(current, home):
    args = current.get("args")
    if (not isinstance(current.get("command"), str) or not current["command"].strip()
            or not isinstance(args, list) or len(args) != 3
            or not all(isinstance(item, str) for item in args) or args[1] != "--credential"):
        return False
    return any(
        args[0] == str(root / directory / "openagent-workbuddy-token-proxy.py")
        and args[2] == str(root / filename)
        for root in config_roots(home)
        for directory, filename in PROFILES
    )


def remove_openagent_mcp_config(source, home):
    """只移除固定服务地址或当前用户代理，保留其他配置；不提供 force。"""
    config = copy.deepcopy(require_object(source, "WorkBuddy MCP 配置"))
    if "mcpServers" not in config:
        return config, False
    servers = require_object(config["mcpServers"], "mcpServers")
    if "openagent" not in servers:
        return config, False
    current = servers["openagent"]
    if not isinstance(current, dict):
        raise ValueError("现有 mcpServers.openagent 不是本插件配置；未清理")
    direct = (not current.get("command") and "args" not in current
              and current.get("url") in OPENAGENT_ENDPOINTS)
    proxy = "url" not in current and is_managed_proxy_config(current, home)
    if not direct and not proxy:
        raise ValueError("现有 mcpServers.openagent 不是本插件目标地址或当前用户代理；未清理")
    del servers["openagent"]
    return config, True


def is_openagent_skill(source, name):
    frontmatter = re.match(r"^---\n([\s\S]*?)\n---\n", source)
    if not frontmatter or name not in OPENAGENT_SKILLS:
        return False
    names = [line[5:].strip() for line in frontmatter[1].split("\n") if line.startswith("name:")]
    return bool(names and names[0] == name and "OpenAgent" in source
                and re.search(r"mcp__openagent__|openagent_(?:run|search|user_guide|account_credits|stop|progress|start)_?", source))


def safe_stat(home, target):
    """逐级 lstat，拒绝用户目录之外的目标和任意路径符号链接。"""
    relative = target.relative_to(home)
    if not relative.parts or ".." in relative.parts:
        raise ValueError("目标必须是当前用户目录内的明确子路径")
    current = home
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("路径包含符号链接，停止清理：" + str(current))
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(info.st_mode):
            raise ValueError("父路径不是目录：" + str(current))
    return info


def read_owned_file(home, target):
    info = safe_stat(home, target)
    if info is None:
        return None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError("目标不是普通文件：" + str(target))
    return {"target": target, "bytes": target.read_bytes(), "mode": info.st_mode & 0o777}


def inspect_skill(home, root, name):
    """只允许分发清单中的文件；未知笔记、目录或链接整体阻止清理。"""
    target = root / name
    info = safe_stat(home, target)
    if info is None:
        return [], []
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("Skill 目标不是目录：" + str(target))
    entry = read_owned_file(home, target / "SKILL.md")
    if not entry or not is_openagent_skill(entry["bytes"].decode("utf-8"), name):
        raise ValueError("无法确认 OpenAgent Skill 归属：" + str(target))
    allowed = {"SKILL.md"}
    if name == "openagent-first-task-router":
        allowed.add("references/result-validation-and-delivery.md")
    if name == "openagent-search-agent":
        allowed.add("assets/close-tab.html")
        allowed.add("scripts/openagent-browser-wrapper.py")
        allowed.add("scripts/openagent-close-tab-server.py")
    files, directories = [], []

    def walk(directory):
        for child in sorted(directory.iterdir()):
            child_info = safe_stat(home, child)
            relative = child.relative_to(target).as_posix()
            if child_info and stat.S_ISDIR(child_info.st_mode) and any(
                    item.startswith(relative + "/") for item in allowed):
                walk(child)
            elif child_info and stat.S_ISREG(child_info.st_mode) and relative in allowed:
                files.append(read_owned_file(home, child))
            else:
                raise ValueError("Skill 中存在未知文件，停止清理：" + str(child))
        directories.append(directory)

    walk(target)
    return files, directories


def inspect_tree(root, target):
    """仅快照已核实归属的原生目录；逐级拒绝链接和特殊文件，便于检测 CLI 后新增内容。"""
    boundary = Path(root.anchor)
    info = safe_stat(boundary, target)
    if info is None:
        return {}
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("原生插件目标不是目录：" + str(target))
    snapshot = {target: ("directory", info.st_mode & 0o777)}
    for child in sorted(target.iterdir()):
        info = safe_stat(boundary, child)
        if stat.S_ISDIR(info.st_mode):
            snapshot.update(inspect_tree(root, child))
        elif stat.S_ISREG(info.st_mode):
            digest = hashlib.sha256()
            with child.open("rb") as stream:
                for block in iter(lambda: stream.read(65536), b""):
                    digest.update(block)
            snapshot[child] = ("file", info.st_mode & 0o777, digest.hexdigest())
        else:
            raise ValueError("原生插件中存在特殊文件，停止清理：" + str(child))
    return snapshot


def inspect_native(root):
    """登记决定实际路径；限定插件私有存储并核对清单，不允许指向共享目录或其他插件。"""
    boundary = Path(root.anchor)
    jsons = []

    def load(relative):
        file = read_owned_file(boundary, root / relative)
        if file is None:
            return {}
        config = parse_json(file["bytes"], "原生插件配置")
        jsons.append(dict(file, original=config, config=copy.deepcopy(config)))
        return jsons[-1]["config"]

    settings = load("settings.json")
    known = load("plugins/known_marketplaces.json")
    installed = load("plugins/installed_plugins.json")
    extra = require_object(settings.get("extraKnownMarketplaces", {}), "extraKnownMarketplaces")
    enabled = require_object(settings.get("enabledPlugins", {}), "enabledPlugins")
    plugins = require_object(installed.get("plugins", {}), "installed plugins")
    market = known.get(MARKETPLACE)
    for item in (extra.get(MARKETPLACE), market):
        if item is not None:
            source = require_object(require_object(item, "Marketplace").get("source"), "Marketplace source")
            if (source.get("source", item.get("type")) != "git"
                    or source.get("repo") not in (None, "")
                    or source.get("url", source.get("path")) not in MARKETPLACE_URLS
                    or ("path" in source and source["path"] != source.get("url", source["path"]))
                    or source.get("ref", "rel") != "rel"):
                raise ValueError("Marketplace 来源冲突；未清理")
    if any(key != PLUGIN_ID and key.endswith("@" + MARKETPLACE) for key in (*plugins, *enabled)):
        raise ValueError("Marketplace 中存在其他插件；未清理")
    records = plugins.get(PLUGIN_ID, [])
    if not isinstance(records, list):
        raise ValueError("OpenAgent 安装登记必须是列表；未清理")
    targets = {}

    def add_target(value, storage, kind):
        if not isinstance(value, str) or not value:
            raise ValueError("插件登记缺少安装目录；未清理")
        target = Path(value)
        parent = root / "plugins" / storage
        if not target.is_absolute() or ".." in target.parts or target == parent or parent not in target.parents:
            raise ValueError("插件登记路径越过私有存储边界；未清理")
        other_paths = []
        if kind == "plugin":
            for key, entries in plugins.items():
                if key != PLUGIN_ID and isinstance(entries, list):
                    other_paths.extend(entry.get("installPath") for entry in entries if isinstance(entry, dict))
        else:
            other_paths.extend(entry.get("installLocation") for key, entry in known.items()
                               if key != MARKETPLACE and isinstance(entry, dict))
        for other in other_paths:
            if isinstance(other, str) and other:
                path = Path(other)
                if path == target or path in target.parents or target in path.parents:
                    raise ValueError("原生目录与其他插件或市场共用；未清理")
        info = safe_stat(boundary, target)
        if info is not None:
            manifest_name = "marketplace.json" if kind == "market" else "plugin.json"
            manifests = [read_owned_file(boundary, target / folder / manifest_name)
                         for folder in (".workbuddy-plugin", ".codebuddy-plugin")]
            manifests = [parse_json(f["bytes"], "插件清单") for f in manifests if f]
            if not manifests or any(m.get("name") != (MARKETPLACE if kind == "market" else "openagent")
                                    for m in manifests):
                raise ValueError("无法确认原生插件目录归属：" + str(target))
            if kind == "market" and any(
                    not isinstance(m.get("plugins"), list) or not m["plugins"]
                    or any(not isinstance(p, dict) or p.get("name") != "openagent" for p in m["plugins"])
                    for m in manifests):
                raise ValueError("Marketplace 清单包含其他插件；未清理")
        targets[target] = inspect_tree(root, target)

    for record in records:
        record = require_object(record, "OpenAgent 安装登记")
        if record.get("scope") != "user":
            raise ValueError("OpenAgent 存在非用户级安装；未清理")
        add_target(record.get("installPath"), "cache", "plugin")
    if market is not None:
        add_target(market.get("installLocation"), "marketplaces", "market")
    # 登记可能仅指向当前版本；检查同一插件的旧版本以及先前卸载遗留的市场目录。
    cache = root / "plugins/cache" / MARKETPLACE / "openagent"
    if safe_stat(boundary, cache) is not None:
        for version in sorted(cache.iterdir()):
            # Finder 元数据不是插件版本；只跳过普通文件，链接仍由 safe_stat 拒绝。
            info = safe_stat(boundary, version)
            if version.name == ".DS_Store" and info and stat.S_ISREG(info.st_mode):
                continue
            add_target(str(version), "cache", "plugin")
    market_path = root / "plugins/marketplaces" / MARKETPLACE
    if safe_stat(boundary, market_path) is not None:
        add_target(str(market_path), "marketplaces", "market")
    extra.pop(MARKETPLACE, None)
    enabled.pop(PLUGIN_ID, None)
    known.pop(MARKETPLACE, None)
    plugins.pop(PLUGIN_ID, None)
    return {"root": root, "jsons": jsons, "trees": targets}


def remaining_native(plan):
    """允许计划内删除并恢复宿主替换文件的已知权限变化；其他变化仍停止。"""
    root = plan["root"]
    jsons, trees = [], {}
    for file in plan["jsons"]:
        current = read_owned_file(Path(root.anchor), file["target"])
        if current is None:
            raise RuntimeError("CLI 后配置文件缺失，卸载未完成")
        config = parse_json(current["bytes"], "原生插件配置")
        # CLI 可能只删除 enabledPlugins，而保留 extraKnownMarketplaces；按目标键分别检查。
        expected = copy.deepcopy(config)
        keys = (("enabledPlugins", "extraKnownMarketplaces") if file["target"].name == "settings.json"
                else ("plugins",) if file["target"].name == "installed_plugins.json" else ())
        for key in keys:
            if key in expected:
                container = require_object(expected[key], key)
                original = file["original"].get(key, {})
                target_key = MARKETPLACE if key == "extraKnownMarketplaces" else PLUGIN_ID
                if target_key in container and container[target_key] != original.get(target_key):
                    raise RuntimeError("原生目标在检查后发生变化，卸载未完成")
                container.pop(target_key, None)
        if file["target"].name == "known_marketplaces.json":
            if MARKETPLACE in expected and expected[MARKETPLACE] != file["original"].get(MARKETPLACE):
                raise RuntimeError("市场登记在检查后发生变化，卸载未完成")
            expected.pop(MARKETPLACE, None)
        if expected != file["config"]:
            raise RuntimeError("其他原生配置内容在检查后发生变化，卸载未完成：" + str(file["target"]))
        mode_changed = current["mode"] != file["mode"]
        # 已核对的宿主原子替换会把 0600 改为 0644；只有实际删除目标键时才接受并恢复。
        if mode_changed and not (file["mode"] == 0o600 and current["mode"] == 0o644
                                 and config != file["original"]):
            raise RuntimeError("原生配置权限在检查后发生变化，卸载未完成：" + str(file["target"]))
        jsons.append(dict(current, mode=file["mode"], config=expected,
                          changed=config != expected or mode_changed))
    for target, before in plan["trees"].items():
        after = inspect_tree(root, target)
        for path, value in after.items():
            if before.get(path) == value:
                continue
            # 宿主也会在已有子目录及使用标记目录中写入数字孤立时间。
            cache = root / "plugins/cache" in target.parents
            orphan = (cache and path.name == ".orphaned_at" and value[0] == "file"
                      and (before.get(path.parent, (None,))[0] == "directory"
                           or path.parent == target / ".in_use")
                      and re.fullmatch(rb"[0-9]{1,20}", path.read_bytes()))
            empty_marker = (cache and path == target / ".in_use" and value[0] == "directory"
                            and all(child.name == ".orphaned_at" for child in path.iterdir()))
            if not orphan and not empty_marker:
                raise RuntimeError("原生目录在检查后发生变化，卸载未完成")
        trees.update(after)
    return jsons, trees


def build_plan(home, roots=None):
    """所有归属检查先于确认、原生 CLI 和个人文件写入。"""
    mcps, files, directories = [], [], []
    roots = config_roots(home) if roots is None else roots
    for root in roots:
        boundary = Path(root.anchor)
        mcp = read_owned_file(boundary, root / "mcp.json")
        owned_http = False
        if mcp:
            original = parse_json(mcp["bytes"], "MCP 配置")
            config, changed = remove_openagent_mcp_config(original, home)
            mcps.append(dict(mcp, config=config, changed=changed))
            if changed:
                server = original["mcpServers"]["openagent"]
                owned_http = server.get("type") == "http" and server.get("url") in OPENAGENT_ENDPOINTS
        for name in OPENAGENT_SKILLS:
            owned, empty_dirs = inspect_skill(boundary, root / "skills", name)
            files.extend(owned)
            directories.extend(empty_dirs)
        sign_in = read_owned_file(boundary, root / "skills/openagent-login/runtime-sign-in.md")
        if sign_in:
            if sign_in["bytes"].splitlines()[:1] != [b"# OpenAgent runtime sign-in"]:
                raise ValueError("无法确认 OpenAgent 登录指引归属：" + str(sign_in["target"]))
            files.append(sign_in)
            directories.append(sign_in["target"].parent)
        for directory, filename in PROFILES:
            inspect_profile(root, boundary, directory, filename, files, directories, owned_http=owned_http)
        for filename in OAUTH_FILE_ALIASES:
            inspect_credential(root, boundary, filename, files)
        browser_dir = root / "browser-tools"
        for name in ("close-tab.html", "close-now.html", "close-all-tabs.html"):
            page = read_owned_file(boundary, browser_dir / name)
            if page:
                # 固定文件名与已知页面特征同时匹配；兼容旧页面，不执行 HTML 或扫描其他文件。
                content = page["bytes"].decode("utf-8")
                marker = "一键清空内置浏览器" if name == "close-now.html" else "artifact-tab__close"
                if ("<!doctype html>" not in content.lower() or "<script>" not in content.lower()
                        or "window.frameElement" not in content or ".remove()" not in content
                        or marker not in content):
                    raise ValueError("无法确认浏览器关闭页面归属：" + str(page["target"]))
                files.append(page)
                directories.append(browser_dir)
    return {"mcps": mcps, "files": files, "directories": list(dict.fromkeys(directories))}


def inspect_credential(root, boundary, filename, files, *, owned_http=False):
    """核对凭据来源和结构；已知别名兼容 MCP 已清除的残留，不输出凭据。"""
    credential = read_owned_file(boundary, root / filename)
    if credential:
        state = parse_json(credential["bytes"], "OAuth 状态")
        # 用户指定且已核对结构的别名独立识别；旧连字符文件仍要求同目录 HTTP 配置证实归属。
        legacy = ((filename in OAUTH_FILE_ALIASES or (owned_http and filename == "openagent-oauth.json"))
                  and "resource" not in state
                  and set(state) <= {"client_id", "refresh_token", "note"}
                  and all(isinstance(state.get(key), str) and state[key].strip()
                          for key in ("client_id", "refresh_token"))
                  and isinstance(state.get("note", ""), str))
        if state.get("resource") not in OPENAGENT_ENDPOINTS and not legacy:
            raise ValueError("无法确认 OAuth 状态归属：" + str(credential["target"]))
        files.append(credential)


def inspect_profile(root, boundary, directory, filename, files, directories, *, owned_http=False):
    """兼容旧版凭据、空锁和代理，只移除已识别文件。"""
    inspect_credential(root, boundary, filename, files, owned_http=owned_http)
    lock = read_owned_file(boundary, root / (filename + ".lock"))
    if lock:
        if lock["bytes"]:
            raise ValueError("无法确认 OAuth 锁文件归属：" + str(lock["target"]))
        files.append(lock)
    proxy_dir = root / directory
    proxy = read_owned_file(boundary, proxy_dir / "openagent-workbuddy-token-proxy.py")
    if proxy:
        content = proxy["bytes"].decode("utf-8")
        base = re.search(r'^OASN_BASE_URL = "([^"]+)"', content, re.MULTILINE)
        if (not content.startswith("#!/usr/bin/env python3") or "OPENAGENT_ENDPOINT" not in content
                or "class TokenManager" not in content or not base
                or not any(endpoint.startswith(base[1] + "/mcp/v1/") for endpoint in OPENAGENT_ENDPOINTS)):
            raise ValueError("无法确认代理文件归属：" + str(proxy["target"]))
        files.append(proxy)
        directories.append(proxy_dir)


def write_json_atomic(file):
    """同目录原子替换并保留权限；失败只移除本次临时文件。"""
    target = file["target"]
    fd, temporary = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            os.fchmod(stream.fileno(), file["mode"])
            json.dump(file["config"], stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def find_codebuddy(home):
    """优先使用 PATH，再查用户命令入口及 macOS 应用内置 CLI；不改全局环境。"""
    command = shutil.which("codebuddy")
    if command:
        return command
    candidates = [home / ".local/bin/codebuddy"]
    for root in (Path("/Applications"), home / "Applications"):
        for name in ("WorkBuddy AI.app", "WorkBuddy.app"):
            candidates.append(root / name / "Contents/Resources/app.asar.unpacked/cli/bin/codebuddy")
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise FileNotFoundError("codebuddy")


def run_native(args, home, config_dir=None):
    """仅对子进程指定实际识别的配置目录，不修改用户环境或采用本机绝对路径。"""
    environment = os.environ.copy()
    directory = str(config_dir if config_dir is not None else config_roots(home)[0])
    environment.update(CODEBUDDY_CONFIG_DIR=directory, WORKBUDDY_CONFIG_DIR=directory)
    # 宿主启动维护会删除其他过期内置市场；卸载子进程只处理已核实的 OpenAgent。
    environment["CODEBUDDY_SKIP_BUILTIN_MARKETPLACE"] = "1"
    return subprocess.run([find_codebuddy(home), *args], cwd=home, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, timeout=30, env=environment)


def native_succeeded(result, kind):
    """部分宿主失败仍返回 0；同时核对明确失败文案和精确的目标不存在响应。"""
    pattern = (r"(?:^|\n)(?:Error: )?Plugin openagent@openagent-workbuddy is not installed\.?(?:\n|$)"
               if kind == "plugin" else
               r"""(?:^|\n)(?:Error: )?Marketplace ['"]?openagent-workbuddy['"]? (?:not found|does not exist)\.?(?:\n|$)""")
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    if re.search(pattern, output) or (kind == "plugin" and re.search(
            r"(?:^|\n)(?:Error: )?Marketplace openagent-workbuddy is not found\.?(?:\n|$)", output)):
        return True
    failed = re.search(r"(?:^|\n)(?:✘ )?Failed to (?:uninstall plugin\(s\)|remove marketplace):", output)
    return result.returncode == 0 and not failed


def remove_native(run_codebuddy):
    """原生操作失败不继续清理；不回显 CLI 输出，不 prune 其他插件依赖。"""
    for kind, args in (
        ("plugin", ["plugin", "uninstall", "openagent@openagent-workbuddy", "--scope", "user", "--yes"]),
        ("marketplace", ["plugin", "marketplace", "remove", "openagent-workbuddy"]),
    ):
        try:
            result = run_codebuddy(args)
        except FileNotFoundError:
            raise RuntimeError("未找到 codebuddy CLI（已检查 PATH、用户入口和 WorkBuddy 应用目录）；个人文件未清理，卸载未完成") from None
        except (OSError, subprocess.SubprocessError):
            raise RuntimeError("原生操作异常或超时；原生状态未确认，个人文件未清理") from None
        if not native_succeeded(result, kind):
            message = ("原生插件卸载失败；未继续清理市场和个人文件" if kind == "plugin" else
                       "Marketplace 移除未确认；原生插件可能已移除，个人文件尚未清理")
            raise RuntimeError(message)


def print_help():
    print("""用法：python3 openagent-workbuddy-uninstall.py [--dry-run] [--yes] [--skip-cli]
自包含卸载器，仅需 Python 3.9+ 标准库。先完全退出 WorkBuddy。
按宿主配置环境变量和当前用户目录识别安装位置，清理 MCP、旧 Skills/OAuth/代理，
以及 browser-tools 内已核实的 close-tab.html、close-now.html、close-all-tabs.html，
以及用户级原生插件/Marketplace 的设置、登记和已核实的缓存、市场目录。
优先 WORKBUDDY_CONFIG_DIR，其次 CODEBUDDY_CONFIG_DIR；未设置时使用当前用户的 .workbuddy。
同时兼容当前用户的 .workbuddy 和 .workbuddy-ai，不扫描其他磁盘目录。
--dry-run  仅预览，不写文件、不调用 CLI
--yes      明确授权跳过交互确认
--skip-cli 仅清理个人安装项，不声称原生插件/Marketplace 已卸载
不支持 --force；冲突必须先人工核对。保留其他插件、共享会话和日志，不撤销远端授权。""")


def uninstall(*, home=None, args=(), run_codebuddy=None):
    """home/CLI 注入仅供隔离测试；命令行不允许指定其他用户目录。"""
    options = set(args)
    if options - {"--yes", "--dry-run", "--skip-cli", "--help"}:
        raise ValueError("未知选项；使用 --help 查看安全参数")
    if "--help" in options:
        print_help()
        return {"help": True}
    home = Path(home if home is not None else Path.home()).resolve(strict=True)
    if home == Path(home.anchor):
        raise ValueError("拒绝把文件系统根目录作为用户目录")
    roots = config_roots(home)
    plan = build_plan(home, roots)
    natives = [inspect_native(root) for root in roots]
    print("OpenAgent 卸载计划（请先完全退出 WorkBuddy）：")
    for file in plan["files"]:
        print("- 删除 " + str(file["target"]))
    for mcp in plan["mcps"]:
        if mcp["changed"]:
            print("- 仅移除 mcpServers.openagent：" + str(mcp["target"]))
    if "--skip-cli" not in options:
        for native in natives:
            print("- 原生配置目录：" + str(native["root"]))
            for file in native["jsons"]:
                if file["original"] != file["config"]:
                    print("- 仅移除 OpenAgent 设置/登记：" + str(file["target"]))
            for target, snapshot in native["trees"].items():
                if snapshot:
                    print("- 清理已核实的原生目录：" + str(target))
    print("- 跳过原生插件/Marketplace 检查" if "--skip-cli" in options else
          "- 卸载用户级原生插件并移除 openagent-workbuddy Marketplace")
    if "--dry-run" in options:
        print("预览完成，未修改文件、未调用 CLI。")
        return {"dry_run": True}
    if "--yes" not in options:
        if not sys.stdin.isatty():
            raise ValueError("非交互终端必须显式使用 --yes；未确认卸载")
        if input("请先完全退出 WorkBuddy。确认卸载以上内容？输入 uninstall 继续：").strip() != "uninstall":
            print("已取消，未执行卸载。")
            return {"cancelled": True}
    if build_plan(home, roots) != plan or [inspect_native(root) for root in roots] != natives:
        raise RuntimeError("目标在检查后发生变化，卸载未完成；未调用 CLI")
    if "--skip-cli" not in options:
        for index, native in enumerate(natives):
            active = native["trees"] or any(f["original"] != f["config"] for f in native["jsons"])
            if index == 0 or active:
                remove_native(run_codebuddy if run_codebuddy is not None else
                              lambda args: run_native(args, home, native["root"]))
    # 确认或 CLI 执行期间改变内容、权限或新增目标，均停止而不覆盖。
    if build_plan(home, roots) != plan:
        raise RuntimeError("目标在检查后发生变化，卸载未完成；未继续清理个人文件")
    native_jsons, native_paths = [], {}
    if "--skip-cli" not in options:
        for native in natives:
            jsons, paths = remaining_native(native)
            native_jsons.extend(jsons)
            native_paths.update(paths)
    for file in native_jsons:
        if file["changed"]:
            write_json_atomic(file)
            if parse_json(file["target"].read_bytes(), "原生配置") != file["config"]:
                raise RuntimeError("原生配置回读不一致，卸载未完成")
    for mcp in plan["mcps"]:
        if mcp["changed"]:
            write_json_atomic(mcp)
            if parse_json(mcp["target"].read_bytes(), "MCP 配置") != mcp["config"]:
                raise RuntimeError("MCP 配置回读不一致，卸载未完成")
    for file in plan["files"]:
        file["target"].unlink()
    for directory in plan["directories"]:
        try:
            directory.rmdir()
        except OSError as error:
            if error.errno not in (errno.ENOENT, errno.ENOTEMPTY, errno.EEXIST):
                raise
    # 深度优先精确删除快照中残留的文件，禁止 rmtree 扩大到新出现的内容。
    for path in sorted(native_paths, key=lambda p: len(p.parts), reverse=True):
        if native_paths[path][0] == "file":
            path.unlink()
        else:
            path.rmdir()
    remaining = build_plan(home, roots)
    if remaining["files"] or any(mcp["changed"] for mcp in remaining["mcps"]):
        raise RuntimeError("仍存在已识别安装项，卸载未完成")
    if "--skip-cli" not in options:
        for root in roots:
            native = inspect_native(root)
            if any(native["trees"].values()) or any(f["original"] != f["config"] for f in native["jsons"]):
                raise RuntimeError("仍存在原生插件设置、登记或目录，卸载未完成")
    completed = "--skip-cli" not in options
    print("已清理已识别的 OpenAgent 用户安装项，原生插件及 Marketplace 卸载已确认。请重新启动 WorkBuddy。"
          if completed else "个人安装项已清理；原生插件和 Marketplace 未检查，不能视为完整卸载。")
    return {"completed": completed}


if __name__ == "__main__":
    try:
        uninstall(args=sys.argv[1:])
    except (OSError, ValueError, RuntimeError, EOFError, KeyboardInterrupt) as error:
        # 解码错误的原始异常可能包含敏感字节，不输出其详情。
        message = "文件编码无效，停止清理" if isinstance(error, UnicodeError) else str(error)
        print("OpenAgent 卸载未完成：" + (message or "用户取消"), file=sys.stderr)
        sys.exit(1)
