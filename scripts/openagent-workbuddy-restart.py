#!/usr/bin/env python3
"""WorkBuddy 独立 Python 后台（Windows 版）：等待完成、退出、直接调试启动及 CDP 发送。

对应 macOS 的 openagent-workbuddy-restart.sh，语义保持一致：
  核验信任 → 等待当前任务 completed → 强制退出 → 带调试端口重启 → CDP 发送一次消息。

Windows 使用 Toolhelp 快照、taskkill 及脱离 Job 的后台进程。
CDP 启用与导航按宿主实际能力检查，结果未知时不补发。

用法：
  python3 openagent-workbuddy-restart.py install --require-existing-trust \
      --wait-for-turn --message-file <请求JSON>
  python3 openagent-workbuddy-restart.py --self-check     # 只读体检
  python3 openagent-workbuddy-restart.py --dry-run ...    # 演练，不杀进程不重启
  python3 openagent-workbuddy-restart.py --worker         # 后台角色（由 install 拉起）
"""

import argparse
import base64
import hashlib
import json
import os
import re
import socket
import sqlite3
import struct
import subprocess
import sys
import time
import urllib.request
from contextlib import closing
from pathlib import Path

IS_WINDOWS = os.name == 'nt'

CONFIG = Path.home() / '.workbuddy'
PORT = 9222
DEFAULT_MESSAGE = 'OpenAgent 已安装，打开新用户引导'
REQUEST = CONFIG / 'wb-relaunch-message.json'
LOG = CONFIG / 'logs' / 'wb-relaunch.log'
TRUST_ORIGIN = b'https://oasn-ow.haimawan.com'
TRUST_NAME = 'openagent'
TARGET_NAME = 'WorkBuddy.exe'


class RestartError(Exception):
    pass


def log(message):
    line = time.strftime('%Y-%m-%d %H:%M:%S') + ' [install] ' + message
    print(line, flush=True)


# ---------------------------------------------------------------- 进程管理（Windows）


def _toolhelp_entries():
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ('dwSize', wintypes.DWORD),
            ('cntUsage', wintypes.DWORD),
            ('th32ProcessID', wintypes.DWORD),
            ('th32DefaultHeapID', ctypes.POINTER(ctypes.c_ulong)),
            ('th32ModuleID', wintypes.DWORD),
            ('cntThreads', wintypes.DWORD),
            ('th32ParentProcessID', wintypes.DWORD),
            ('pcPriClassBase', ctypes.c_long),
            ('dwFlags', wintypes.DWORD),
            ('szExeFile', wintypes.WCHAR * 260),
        ]

    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]

    snapshot = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == wintypes.HANDLE(-1).value:
        raise RestartError('PROCESS_SNAPSHOT_FAILED')
    entries = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not k32.Process32FirstW(snapshot, ctypes.byref(entry)):
            raise RestartError('PROCESS_SNAPSHOT_FAILED')
        while True:
            entries.append((int(entry.th32ProcessID), entry.szExeFile,
                            int(entry.th32ParentProcessID)))
            if not k32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        k32.CloseHandle(snapshot)
    return entries


def app_pids():
    return [pid for pid, exe, _ in _toolhelp_entries() if exe.lower() == TARGET_NAME.lower()]


def app_main_pid():
    """Electron 子进程与主进程同名；仅认唯一的进程树根。"""
    entries = _toolhelp_entries()
    pids = {pid for pid, exe, _ in entries if exe.lower() == TARGET_NAME.lower()}
    roots = [pid for pid, _, parent in entries if pid in pids and parent not in pids]
    if len(roots) != 1:
        raise RestartError('APP_IDENTITY_NOT_UNIQUE')
    return roots[0]


def in_job():
    """只读检测当前进程所属 Job；不修改宿主安全设置。"""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    assigned = wintypes.BOOL()
    if not k32.IsProcessInJob(k32.GetCurrentProcess(), None, ctypes.byref(assigned)):
        raise RestartError('JOB_STATUS_UNAVAILABLE')
    return bool(assigned.value)


def process_image_path(pid):
    """取进程可执行文件全路径；失败返回 None。"""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL('kernel32', use_last_error=True)
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    ]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(size.value)
        if not k32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return buffer.value
    finally:
        k32.CloseHandle(handle)


def app_executable(pid=None):
    """使用当前主实例真实路径，支持 D 盘等自定义安装位置。"""
    path = process_image_path(pid if pid is not None else app_main_pid())
    if path and Path(path).is_file():
        return Path(path)
    raise RestartError('APP_EXECUTABLE_UNAVAILABLE')


def quit_app(dry_run=False):
    pids = app_pids()
    log('强制退出 WorkBuddy 相关进程：' + ','.join(str(p) for p in sorted(pids)))
    if dry_run:
        return pids
    for _ in range(2):
        for pid in app_pids():
            try:
                subprocess.run(['taskkill', '/F', '/PID', str(pid)],
                               capture_output=True, timeout=15)
            except (OSError, subprocess.SubprocessError):
                pass
        for _ in range(16):
            if not app_pids():
                return pids
            time.sleep(0.5)
    raise RestartError('OLD_PROCESS_STILL_ALIVE')


def start_app(executable, dry_run=False):
    """直接启动二进制并显式传调试变量。"""
    env = {**os.environ, 'WORKBUDDY_REMOTE_DEBUGGING_PORT': str(PORT)}
    for key in ('ELECTRON_RUN_AS_NODE', 'NODE_OPTIONS', 'NODE_REPL_EXTERNAL_MODULE'):
        env.pop(key, None)
    log('GUI 启动环境已清理 Node 模式变量')
    cmd = [str(executable), '--remote-debugging-port=%d' % PORT]
    if dry_run:
        log('演练：将执行 ' + ' '.join(cmd))
        return None
    child = subprocess.Popen(cmd, env=env, cwd=str(Path.home()),
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, close_fds=True,
                             creationflags=0x00000008 | 0x00000200)
    log('直接启动 WorkBuddy PID=%d，调试端口=%d' % (child.pid, PORT))
    return child


# ---------------------------------------------------------------- 状态与信任


def turn_status(session_id):
    """只读当前任务状态，不查询消息正文或凭据。"""
    path = CONFIG / 'workbuddy.db'
    if path.is_symlink() or not path.is_file():
        raise RestartError('TURN_STORE_UNAVAILABLE')
    try:
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
            row = db.execute('SELECT status FROM sessions WHERE id = ? AND deleted_at IS NULL',
                             (session_id,)).fetchone()
    except sqlite3.Error:
        raise RestartError('TURN_STORE_UNAVAILABLE') from None
    if not row:
        raise RestartError('TURN_NOT_FOUND')
    return row[0]


def wait_for_turn(request):
    """前台已经返回；后台每秒等待 completed，没有超时，失败不退出应用。"""
    session_id = request['session_id']
    if not session_id:
        return
    log('等待当前任务 completed')
    while True:
        if request['old_pid'] != app_main_pid():
            raise RestartError('TURN_APP_CHANGED')
        state = turn_status(session_id)
        if state == 'completed':
            return
        if state not in ('working', 'planning', 'pending'):
            raise RestartError('TURN_NOT_COMPLETED')
        time.sleep(1)


def verify_trust():
    """仅核验安装程序已登记的固定来源信任；不读取 MCP 正文或自动授予其他来源信任。"""
    path = CONFIG / 'mcp-approvals.json'
    if path.is_symlink():
        raise RestartError('TRUST_FILE_SYMLINK')
    try:
        data = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        raise RestartError('TRUST_NOT_VERIFIED') from None
    key = hashlib.sha256(TRUST_ORIGIN).hexdigest() + '::' + TRUST_NAME
    stamp = data.get(key) if isinstance(data, dict) else None
    if type(stamp) is not int or stamp <= 0:
        raise RestartError('TRUST_NOT_VERIFIED')


def verify_enabled_config():
    """缺少启用 API 时仅检查目标开关，不把配置存在视为连接成功。"""
    try:
        data = json.loads((CONFIG / 'mcp.json').read_text(encoding='utf-8-sig'))
        server = data['mcpServers']['openagent']
        if not isinstance(server, dict) or not server:
            raise ValueError()
        if ('disabled' in server and server['disabled'] is not False or
                'enabled' in server and server['enabled'] is not True):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        raise RestartError('MCP_ENABLED_CONFIG_NOT_VERIFIED') from None


def write_private(path, text):
    """请求保存在当前用户目录，沿用该目录的 Windows ACL。"""
    path.write_text(text, encoding='utf-8')


# ---------------------------------------------------------------- CDP


class CDP:
    """标准库实现本机 CDP 通信；保留 60 秒等待及原有错误语义。"""

    def __init__(self, ws):
        hostport, self.path = ws[5:].split('/', 1)
        self.path = '/' + self.path
        host, port = hostport.split(':')
        self.sock = socket.create_connection((host, int(port)), timeout=10)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall(('GET %s HTTP/1.1\r\nHost: %s:%s\r\nUpgrade: websocket\r\n'
                           'Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n'
                           'Sec-WebSocket-Version: 13\r\n\r\n'
                           % (self.path, host, port, key)).encode())
        buffer = b''
        while b'\r\n\r\n' not in buffer:
            part = self.sock.recv(4096)
            if not part:
                self.sock.close()
                raise RuntimeError('CDP closed')
            buffer += part
        if b'101' not in buffer.split(b'\r\n')[0]:
            raise RuntimeError('WS handshake failed')
        self._id = 0

    def _send(self, payload):
        data = json.dumps(payload).encode()
        header = bytearray([0x81])
        length = len(data)
        mask = os.urandom(4)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack('>H', length)
        else:
            header.append(0x80 | 127)
            header += struct.pack('>Q', length)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _recv(self):
        def readn(count):
            chunk = b''
            while len(chunk) < count:
                part = self.sock.recv(count - len(chunk))
                if not part:
                    raise RuntimeError('CDP closed')
                chunk += part
            return chunk

        b0, b1 = readn(2)
        length = b1 & 0x7F
        if length == 126:
            length = struct.unpack('>H', readn(2))[0]
        elif length == 127:
            length = struct.unpack('>Q', readn(8))[0]
        mask = readn(4) if b1 & 0x80 else None
        payload = readn(length)
        if mask:
            payload = bytes(c ^ mask[i % 4] for i, c in enumerate(payload))
        return b0 & 0x0F, payload

    def call(self, method, params=None, timeout=60):
        self._id += 1
        message_id = self._id
        self._send({'id': message_id, 'method': method, 'params': params or {}})
        self.sock.settimeout(timeout)
        while True:
            opcode, payload = self._recv()
            if opcode == 0x8:
                raise RuntimeError('CDP closed')
            if opcode not in (0x1, 0x2):
                continue
            message = json.loads(payload.decode())
            if message.get('id') == message_id:
                if 'error' in message:
                    raise RuntimeError('%s: %s' % (method, message['error']))
                return message.get('result', {})

    def evaluate(self, expression, await_promise=True):
        result = self.call('Runtime.evaluate', {
            'expression': expression, 'awaitPromise': await_promise,
            'returnByValue': True, 'userGesture': True,
        })
        if result.get('exceptionDetails'):
            raise RuntimeError('JS exception')
        return result.get('result', {}).get('value')

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def find_wb():
    for _ in range(80):
        try:
            with urllib.request.urlopen('http://127.0.0.1:%d/json/list' % PORT, timeout=3) as response:
                pages = [t for t in json.loads(response.read().decode()) if t.get('type') == 'page']
        except Exception:
            pages = []
        for target in pages:
            ws = target.get('webSocketDebuggerUrl')
            if not ws:
                continue
            client = None
            try:
                client = CDP(ws)
                if client.evaluate('typeof globalThis.wb') == 'object':
                    return client
            except Exception:
                pass
            if client:
                client.close()
        time.sleep(0.5)
    return None


WATCH_JS = r'''(message=>{const api=wb.conversations;const original=api.create;const state={id:null,pending:false,api,original};const wrapped=async function(params){const text=(params.promptContentBlocks||[]).filter(b=>b.type==='text').map(b=>b.text||'').join('');const matches=text.trim()===message.trim();if(matches)state.pending=true;try{const result=await original.call(this,params);if(matches&&result?.info?.id)state.id=result.info.id;return result;}finally{if(matches)state.pending=false;}};state.wrapped=wrapped;globalThis.__wbRestartCreated=state;api.create=wrapped;return api.create===wrapped;})'''

SEND_JS = r'''(async message=>{
    await wb.conversations.prepareInput({target:{type:"new"},contentBlocks:[{type:"text",text:message}]});
    const stores=new Set();
    for(const el of document.querySelectorAll('textarea,[contenteditable=""],[contenteditable="true"]')){
        const rect=el.getBoundingClientRect();
        if(el.offsetParent===null||rect.width<=120||rect.height<16)continue;
        const key=Object.keys(el).find(k=>k.startsWith('__reactFiber$'));
        for(let fiber=el[key];fiber;fiber=fiber.return){
            const props=fiber.memoizedProps;
            const store=props?.store??props?.value;
            if(typeof store?.api?.send==='function'&&typeof store.getSnapshot==='function'){
                stores.add(store);break;
            }
        }
    }
    if(stores.size!==1)return {ok:false,reason:"input-store-not-unique"};
    const store=[...stores][0],snapshot=store.getSnapshot(),draft=snapshot.draft;
    if(!draft?.sessionId?.startsWith('__home__:'))return {ok:false,reason:"input-target-changed"};
    const blocks=draft.content.blocks;
    if(draft.references.length||blocks.some(b=>b.type!=='text')||blocks.map(b=>b.text??'').join('')!==message)
        return {ok:false,reason:"input-draft-changed"};
    if(snapshot.status.disabled||snapshot.status.hostDisabled||snapshot.status.phase!=='idle'||
       draft.content.hasProcessingContent||!snapshot.capabilities.sendWired)
        return {ok:false,reason:"input-not-ready"};
    const result=await store.api.send();
    return {ok:result?.ok===true};
})'''


ENABLE_JS = r'''(async()=>{
    const out={enable:'unavailable',goto:'skip'},c=wb.connectors||{};
    let receiver,method;
    if(typeof c.setCustomMcpServerEnabled==='function'){
        receiver=c;method=c.setCustomMcpServerEnabled;out.enable='setCustomMcpServerEnabled';
    }else if(typeof wb.mcp?.setEnabled==='function'){
        receiver=wb.mcp;method=wb.mcp.setEnabled;out.enable='mcp.setEnabled';
    }else if(typeof c.setEnabled==='function'){
        receiver=c;method=c.setEnabled;out.enable='connectors.setEnabled';
    }
    if(method){
        const result=await method.call(receiver,"openagent",true);
        if(result===false||result?.ok===false||result?.success===false)throw new Error('MCP_ENABLE_REJECTED');
    }
    if(typeof wb.navigation?.goto==='function'){
        await wb.navigation.goto({tab:"home"});out.goto='ok';
    }
    return out;
})()'''


def _probe(client, expression, default=None):
    """只用于发送后的确认与清理；未知结果不触发补发。"""
    try:
        return client.evaluate(expression)
    except Exception:  # noqa: BLE001
        return default


def send_message(request):
    """通过输入状态和发送 API 提交一次消息，确认创建后导航；未知结果不补发。"""
    message = request['message']
    log('等待 CDP 端口 %d …' % PORT)
    for _ in range(80):
        try:
            probe = socket.create_connection(('127.0.0.1', PORT), timeout=2)
            probe.close()
            log('TCP 端口已连通')
            break
        except OSError:
            time.sleep(0.5)
    else:
        log('[!] CDP 端口 40 秒超时')
        return False
    log('查找 wb 渲染页 …')
    client = find_wb()
    if not client:
        log('[!] 未找到 wb 渲染页')
        return False
    log('已连接 wb 渲染页')

    try:
        stages = client.evaluate(ENABLE_JS)
        methods = ('setCustomMcpServerEnabled', 'mcp.setEnabled', 'connectors.setEnabled', 'unavailable')
        if not isinstance(stages, dict) or stages.get('enable') not in methods or stages.get('goto') not in ('ok', 'skip'):
            raise RestartError('MCP_ENABLE_NOT_CONFIRMED')
        if stages['enable'] == 'unavailable':
            verify_enabled_config()
            log('[i] 缺少启用 API；已核验配置开关，实际连接和工具加载仍待新任务验证')
        if stages.get('goto') == 'ok':
            time.sleep(1.4)
        can_navigate = stages['goto'] == 'ok'

        if client.evaluate(WATCH_JS + '(' + json.dumps(message) + ')') is not True:
            raise RestartError('无法捕获新会话，停止发送')

        sent = client.evaluate(SEND_JS + '(' + json.dumps(message) + ')')
        if not isinstance(sent, dict) or sent.get('ok') is not True:
            raise RestartError('SEND_API_NOT_CONFIRMED')
        log('发送 API 已确认提交')

        target_id = None
        for _ in range(60):
            target_id = _probe(client, 'globalThis.__wbRestartCreated.id')
            if isinstance(target_id, str) and target_id:
                break
            target_id = None
            time.sleep(0.5)
        if not target_id:
            log('[!] 未确认新会话，停止；不补发消息')
            return False
        time.sleep(1)
        log('本次新会话已创建: ' + str(target_id))
        if not can_navigate:
            log('[i] 无导航 API，新会话已创建但保持当前视图')
            return True
        for _ in range(3):
            _probe(client, '(async()=>{await wb.navigation.goto({tab:"conversation",path:'
                          + json.dumps(str(target_id)) + '});return true;})()')
            for _ in range(12):
                time.sleep(0.25)
                if _probe(client, 'wb.conversations.currentId') == target_id:
                    log('[OK] 已切换到本次新会话')
                    return True
        log('[!] 新会话已创建，但界面跳转未确认；不补发消息')
        return True
    finally:
        try:
            _probe(client, '(()=>{const s=globalThis.__wbRestartCreated;if(s){'
                           'if(s.api.create===s.wrapped)s.api.create=s.original;'
                           'delete globalThis.__wbRestartCreated;}})()')
        finally:
            client.close()


# ---------------------------------------------------------------- 主流程


def worker():
    """确认不属于宿主 Job 后才退出旧应用，异常清理请求正文。"""
    try:
        if in_job():
            raise RestartError('WORKER_STILL_IN_JOB')
        request = json.loads(REQUEST.read_text(encoding='utf-8-sig'))
        log('Python 后台开始 PID=%d' % os.getpid())
        wait_for_turn(request)
        if request['old_pid'] != app_main_pid():
            raise RestartError('TURN_APP_CHANGED')
        verify_trust()
        executable = app_executable(request['old_pid'])
        if executable != Path(request['executable']):
            raise RestartError('TURN_APP_CHANGED')
        quit_app()
        time.sleep(2)
        if app_pids():
            raise RestartError('OLD_PROCESS_STILL_ALIVE')
        log('旧实例已退出')
        start_app(executable)
        ok = send_message(request)
        log('流程结束（发送结果=%s）' % ('成功' if ok else '未确认'))
        sys.exit(0 if ok else 1)
    finally:
        try:
            REQUEST.unlink()
        except OSError:
            pass


def self_check():
    """只读体检：信任、可执行文件、进程、任务状态、调试端口。"""
    checks = []

    def record(name, ok, detail=''):
        checks.append((name, ok, detail))

    try:
        verify_trust()
        record('信任登记', True, 'openagent 已受信')
    except RestartError as error:
        record('信任登记', False, str(error))

    pids = app_pids()
    record('WorkBuddy 进程', bool(pids), ','.join(map(str, pids)) or '未运行')

    try:
        executable = app_executable()
        record('可执行文件', True, str(executable))
    except RestartError as error:
        record('可执行文件', False, str(error))

    session_id = os.environ.get('CODEBUDDY_SESSION_ID', '')
    if session_id:
        try:
            state = turn_status(session_id)
            record('当前任务状态', state in ('working', 'planning', 'pending', 'completed'),
                   '%s → %s' % (session_id[:8], state))
        except RestartError as error:
            record('当前任务状态', False, str(error))
    else:
        record('当前任务状态', True, '无 CODEBUDDY_SESSION_ID（跳过）')

    try:
        probe = socket.create_connection(('127.0.0.1', PORT), timeout=2)
        probe.close()
        record('调试端口', True, '%d 已被占用（可能已有调试实例）' % PORT)
    except OSError:
        record('调试端口', True, '%d 空闲' % PORT)

    record('日志路径', True, str(LOG))
    width = max(len(name) for name, _, _ in checks)
    for name, ok, detail in checks:
        print('%-4s %-*s %s' % ('[OK]' if ok else '[!!]', width, name, detail))
    return all(ok for _, ok, _ in checks)


def launch(args):
    if not args.require_existing_trust and not (args.dry_run or args.self_check):
        raise RestartError('EXISTING_TRUST_PROTOCOL_REQUIRED')
    if args.message_file is not None:
        message_path = Path(args.message_file)
        if not message_path.is_absolute() or not message_path.is_file():
            raise RestartError('MESSAGE_FILE_PATH_INVALID: --message-file 必须是已存在的 JSON 文件绝对路径')
        try:
            data = json.loads(message_path.read_text(encoding='utf-8-sig'))
        except (json.JSONDecodeError, UnicodeError):
            raise RestartError('MESSAGE_FILE_JSON_INVALID: 消息文件必须使用 UTF-8 编码并包含合法 JSON') from None
        if not isinstance(data, dict):
            raise RestartError('MESSAGE_FILE_OBJECT_REQUIRED: 消息文件必须包含 JSON 对象')
        message = data.get('message')
    else:
        message = args.message
    if not isinstance(message, str) or not message.strip():
        raise RestartError('EMPTY_MESSAGE: message 必须是非空字符串')

    session_id = os.environ.get('CODEBUDDY_SESSION_ID', '')
    if session_id or args.wait_for_turn:
        if not re.fullmatch(r'[0-9a-fA-F-]{36}', session_id):
            raise RestartError('TURN_CONTEXT_REQUIRED')
        state = turn_status(session_id)
        if state not in ('working', 'planning', 'pending'):
            raise RestartError('TURN_NOT_ACTIVE: %s' % state)
        if args.dry_run:
            log('演练：当前任务状态 %s，安装时会由后台等待 completed' % state)

    old_pid = app_main_pid()
    executable = app_executable(old_pid)
    log('目标可执行文件：%s' % executable)
    verify_trust()
    log('已核验已有固定来源信任：openagent')

    if args.dry_run:
        log('演练模式：以下为将要执行的动作，不会真正执行')
        quit_app(dry_run=True)
        start_app(executable, dry_run=True)
        log('演练完成')
        return

    for directory in (CONFIG, LOG.parent):
        if not directory.is_dir():
            directory.mkdir(parents=True, exist_ok=True)
    write_private(REQUEST, json.dumps({
        'message': message,
        'session_id': session_id,
        'old_pid': old_pid,
        'executable': str(executable),
    }, ensure_ascii=False))

    try:
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        if in_job():
            flags |= 0x01000000  # CREATE_BREAKAWAY_FROM_JOB，拒绝时不降级重试。
        with open(LOG, 'a', encoding='utf-8') as output:
            child = subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), '--worker'],
                stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                cwd=str(Path.home()), close_fds=True, creationflags=flags,
            )
    except Exception:
        REQUEST.unlink(missing_ok=True)
        raise
    log('已创建独立 Python 后台 PID=%d（尚未验证存活或重启）' % child.pid)
    log('全程日志：%s' % LOG)
    log('当前任务完成后由后台重启；请结束当前回复' if session_id else '后台将直接重启')


def main():
    if not IS_WINDOWS:
        raise RestartError('此脚本仅适用于 Windows；macOS 请使用现有 .sh 入口')
    if sys.argv[1:] == ['--worker']:
        worker()
        return
    parser = argparse.ArgumentParser(description='独立 Python 后台重启 WorkBuddy（Windows 版）')
    parser.add_argument('mode', choices=['install', 'help'], nargs='?', default='help')
    parser.add_argument('--server', choices=['openagent'], default='openagent')
    parser.add_argument('--message-file')
    parser.add_argument('--message', default=DEFAULT_MESSAGE)
    parser.add_argument('--wait-for-turn', action='store_true')
    parser.add_argument('--require-existing-trust', action='store_true')
    parser.add_argument('--dry-run', action='store_true', help='演练：不杀进程、不重启')
    parser.add_argument('--self-check', action='store_true', help='只读体检')
    args = parser.parse_args()

    if args.self_check:
        sys.exit(0 if self_check() else 1)
    if args.mode == 'help':
        parser.print_help()
        return
    launch(args)


if __name__ == '__main__':
    try:
        main()
    except RestartError as error:
        log(str(error))
        sys.exit(1)
    except PermissionError:
        log('权限不足，请通过 WorkBuddy 原生授权处理；结果未确认时不要重复重启或发送。')
        sys.exit(1)
    except Exception as error:  # noqa: BLE001
        log('执行失败：%s；结果未确认，不要重复重启或发送。' % type(error).__name__)
        sys.exit(1)
