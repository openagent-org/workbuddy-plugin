#!/usr/bin/env python3
"""第 4 步单进程安装：Token 仅在程序和私有文件中流转，不访问其他客户端。"""

import argparse, sys
import base64, hashlib, json, math, os, tempfile, time, urllib.error, urllib.parse, urllib.request
import http.server, secrets, webbrowser
from contextlib import contextmanager, ExitStack
from pathlib import Path

def state(target):
    """仅取元数据检查配置变化，不读取含 Token 的文件正文。"""
    stat = target.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)

def save(target, data, before, permissions=0o600):
    """私有原子写入；原文件变化时停止，保留外部修改。"""
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.openagent-', dir=target.parent) as directory:
        temporary = Path(directory) / target.name
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        temporary.chmod(permissions)
        stamp = state(temporary)
        if target.is_symlink() or (target.read_bytes() if target.exists() else None) != before:
            raise SystemExit('文件已被其他进程修改，停止并重新检查')
        os.replace(temporary, target)
        return stamp

@contextmanager
def sign_in(saved, url, scope):
    """独占回调端口完成一次交互授权；退出时释放监听，不保存中间授权材料。"""
    previous = json.loads(saved) if saved is not None else {}
    if saved is not None and previous.get('resource') != url:
        raise SystemExit('已有凭据不属于当前 REL，停止')
    client_id = previous.get('client_id')
    if client_id is not None and (not isinstance(client_id, str) or not client_id.strip()):
        raise SystemExit('已有客户端标识无效，停止')
    expected_state, outcome = secrets.token_urlsafe(32), {}

    class Callback(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != '/callback':
                self.send_error(404)
                return
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            valid_state = len(query.get('state', [])) == 1 and secrets.compare_digest(
                query['state'][0].encode(), expected_state.encode())
            if not valid_state or ('code' in query and 'error' in query):
                outcome['status'] = 'invalid'
            elif query.get('error') == ['access_denied']:
                outcome['status'] = 'cancelled'
            elif 'error' in query or len(query.get('code', [])) != 1 or not query['code'][0].strip():
                outcome['status'] = 'failed'
            else:
                outcome.update(status='authorized', code=query['code'][0])
            self.send_response(200 if outcome['status'] == 'authorized' else 400)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.end_headers()
            self.wfile.write('请返回 WorkBuddy 查看授权结果。'.encode())

        def log_message(self, *args):
            pass

    class CallbackServer(http.server.HTTPServer):
        allow_reuse_address = os.name != 'nt'

        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(1)
            return connection, address

    try:
        server = CallbackServer(('127.0.0.1', 52961), Callback)
    except OSError:
        raise SystemExit('无法监听登录回调端口，可能已有登录流程；停止且不重复打开页面') from None
    with server:
        server.timeout = 1
        redirect_uri = 'http://127.0.0.1:52961/callback'
        if client_id is None:
            request = urllib.request.Request('https://openagent.org/owner-oauth/register',
                data=json.dumps({'client_name': 'workbuddy', 'redirect_uris': [redirect_uri],
                    'grant_types': ['authorization_code', 'refresh_token'], 'response_types': ['code'],
                    'token_endpoint_auth_method': 'none', 'scope': scope}).encode(),
                headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=30) as response: registration = json.load(response)
            client_id = registration.get('client_id')
            if not isinstance(client_id, str) or not client_id.strip():
                raise SystemExit('OAuth 注册未返回有效客户端标识，停止')
        verifier = secrets.token_urlsafe(32)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        parameters = {'response_type': 'code', 'client_id': client_id, 'redirect_uri': redirect_uri,
            'resource': url, 'scope': scope, 'state': expected_state,
            'code_challenge': challenge, 'code_challenge_method': 'S256'}
        try:
            opened = webbrowser.open('https://openagent.org/owner-oauth/authorize?' + urllib.parse.urlencode(parameters))
        except (OSError, webbrowser.Error):
            raise SystemExit('无法打开 OpenAgent 登录页面，停止') from None
        if not opened:
            raise SystemExit('无法打开 OpenAgent 登录页面，停止')
        print('SIGN_IN_OPENED', flush=True)
        deadline = time.monotonic() + 180
        while not outcome and time.monotonic() < deadline:
            server.handle_request()
        if not outcome:
            print('SIGN_IN_TIMED_OUT', flush=True)
            raise SystemExit('等待 OpenAgent 登录超时，停止')
        if outcome['status'] == 'cancelled':
            print('SIGN_IN_CANCELLED', flush=True)
            raise SystemExit('用户拒绝或取消 OpenAgent 授权，停止')
        if outcome['status'] != 'authorized':
            raise SystemExit('OpenAgent 授权回调校验失败，停止')
        yield client_id, outcome['code'], verifier

def main():
    """exchange 从标准输入取得授权参数；resume/refresh 仅使用私有凭据，失败不重放请求。"""
    parser = argparse.ArgumentParser(description='交换 Token、配置 MCP、验证连接并登记信任；仅输出状态。')
    parser.add_argument('--mode', choices=('exchange', 'resume', 'refresh', 'sign-in'), default='exchange')
    mode = parser.parse_args().mode
    client_id = code = verifier = ''
    if mode == 'exchange':
        try:
            values = json.load(sys.stdin)
            client_id, code, verifier = (values[key] for key in ('client_id', 'code', 'verifier'))
            if any(not isinstance(value, str) or not value or value.startswith('<') for value in (client_id, code, verifier)):
                raise ValueError()
        except (OSError, ValueError, TypeError, KeyError):
            raise SystemExit('请通过标准输入 JSON 提供有效 client_id、code 和 verifier，停止；不输出输入内容') from None

    url = 'https://openagent.org/mcp/v1/open-agent'
    path = Path.home() / '.workbuddy' / 'mcp.json'
    credential = path.with_name('openagent-rel-oauth.json')
    scope = 'agent.discover agent.invoke artifact.read'
    stage = '检查配置'
    sign_in_authorized = False
    cleanup = ExitStack()

    try:
        if mode not in ('exchange', 'resume', 'refresh', 'sign-in'): raise SystemExit('安装模式无效，停止')
        if path.is_symlink() or credential.is_symlink(): raise SystemExit('配置或凭据文件是符号链接，停止')
        mcp_stamp = state(path) if path.exists() else None
        before = path.read_bytes() if path.exists() else None
        data = json.loads(before) if before is not None else {}
        if mode == 'sign-in' and data.get('mcpServers', {}).get('openagent', {}).get('url') != url:
            raise SystemExit('运行时登录要求已有当前 REL 的 OpenAgent MCP 配置，停止')
        entry = data.setdefault('mcpServers', {}).setdefault('openagent', {})
        if mode == 'sign-in' and entry.get('disabled') is True:
            raise SystemExit('OpenAgent 连接已禁用，停止；请先在 WorkBuddy 中启用连接')
        if ('command' in entry or 'args' in entry or entry.get('type', 'http') != 'http'
                or entry.get('url', url) != url):
            raise SystemExit('openagent 已有其他类型或来源配置，停止')
        headers = entry.setdefault('headers', {})
        if not isinstance(headers, dict): raise SystemExit('MCP 请求头类型错误，停止')
        saved = credential.read_bytes() if credential.exists() else None
        if mode == 'sign-in':
            stage = '登录授权'
            client_id, code, verifier = cleanup.enter_context(sign_in(saved, url, scope))
        if mode in ('exchange', 'sign-in'):
            if any(not value or value.startswith('<') for value in (client_id, code, verifier)):
                raise SystemExit('请填入本次 CLIENT_ID、CODE 和 VERIFIER，停止')
            form = {'grant_type': 'authorization_code', 'code': code, 'client_id': client_id,
                    'code_verifier': verifier, 'redirect_uri': 'http://127.0.0.1:52961/callback', 'resource': url}
        else:
            token = json.loads(saved) if saved is not None else {}
            if token.get('resource') != url: raise SystemExit('缺少本次安装的私有凭据，停止')
            client_id = token['client_id']
            form = {'grant_type': 'refresh_token', 'refresh_token': token['refresh_token'],
                    'client_id': client_id, 'resource': url}
        if mode != 'resume':
            stage = '交换 Token' if mode in ('exchange', 'sign-in') else '刷新 Token'
            request = urllib.request.Request('https://openagent.org/owner-oauth/token',
                data=urllib.parse.urlencode(form).encode(), headers={'Content-Type': 'application/x-www-form-urlencoded'})
            with urllib.request.urlopen(request, timeout=30) as response: token = json.load(response)
            if 'error' in token: raise SystemExit(stage + '失败，停止；不重试本次请求')
            for key in ('access_token', 'refresh_token'):
                if not isinstance(token.get(key), str) or not token[key].strip():
                    raise SystemExit('Token 响应缺少有效凭据，停止')
            now = time.time()
            if 'expires_in' in token:
                expires = token['expires_in']
                if type(expires) not in (int, float) or not math.isfinite(expires) or expires <= 0:
                    raise SystemExit('Token 有效期无效，停止')
                expires_at = now + expires
            else:
                # 静态兼容响应省略 TTL；JWT exp 仅用于到期元数据，认证仍由 MCP 服务验证。
                parts = token['access_token'].split('.')
                if len(parts) != 3: raise SystemExit('Token 缺少有效到期信息，停止')
                payload = json.loads(base64.urlsafe_b64decode(parts[1] + '=' * (-len(parts[1]) % 4)))
                expires_at = payload.get('exp')
                if type(expires_at) not in (int, float) or not math.isfinite(expires_at) or expires_at <= now:
                    raise SystemExit('Token 缺少有效到期信息，停止')
            if not set(scope.split()).issubset(token.get('scope', '').split()):
                raise SystemExit('Token scope 不足，停止')
            token = {'version': 2, 'client_id': client_id, 'resource': url, 'scope': scope,
                     'access_token': token['access_token'], 'refresh_token': token['refresh_token'],
                     'expires_at': expires_at}
            stage = '保存凭据'
            save(credential, token, saved)
            if mode == 'sign-in': sign_in_authorized = True
            print('TOKEN_SAVED')
            if mode == 'sign-in': print('SIGN_IN_AUTHORIZED', flush=True)
        if not isinstance(token.get('access_token'), str) or not token['access_token'].strip():
            raise SystemExit('私有凭据缺少有效 Token，停止')
        stage = '配置 MCP'
        headers.update({'Authorization': 'Bearer ' + token['access_token'],
            'X-OASN-MCP-Content-Mode': 'text-compatible', 'X-OASN-MCP-Legacy-SSE': 'enabled'})
        entry.update({'type': 'http', 'url': url, 'timeout': 86400000})
        if before is not None and data == json.loads(before) and path.stat().st_mode & 0o777 == 0o600:
            print('CONFIG_UNCHANGED')
        else:
            mcp_stamp = save(path, data, before)
            print('CONFIG_WRITTEN')
        stage = '验证连接'
        request = urllib.request.Request(url, data=json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2025-11-25', 'capabilities': {},
                       'clientInfo': {'name': 'workbuddy', 'version': '1.0'}}}).encode(),
            headers={'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream', **headers})
        with urllib.request.urlopen(request, timeout=30) as response:
            if 'text/event-stream' in response.headers.get('Content-Type', ''):
                lines, result = [], None
                for line in response:
                    line = line.decode().rstrip('\r\n')
                    if line.startswith('data:'): lines.append(line[5:].lstrip())
                    elif not line and lines:
                        result = json.loads('\n'.join(lines))
                        if result.get('id') == 1: break
                        lines = []
            else: result = json.load(response)
        if not isinstance(result, dict) or result.get('id') != 1 or 'error' in result:
            raise SystemExit('MCP 初始化失败，停止；使用 resume 恢复，不重复交换 Token')
        if not isinstance(result.get('result', {}).get('protocolVersion'), str) or not isinstance(result['result'].get('capabilities'), dict):
            raise SystemExit('MCP 初始化响应无效，停止；使用 resume 恢复')
        print('MCP_VERIFIED')
        stage = '登记信任'
        # 来源已由内存中的 entry 校验；此后不再读取 MCP 正文。
        approvals = path.with_name('mcp-approvals.json')
        if approvals.is_symlink(): raise SystemExit('信任文件是符号链接，停止')
        if state(path) != mcp_stamp: raise SystemExit('MCP 配置已变化，停止信任')
        old = approvals.read_bytes() if approvals.exists() else None
        content = (old or b'').strip(b' \t\r\n') or b'{}'
        records = json.loads(content)
        key = hashlib.sha256(b'https://openagent.org').hexdigest() + '::openagent'
        stamp = records.setdefault(key, int(time.time() * 1000))
        if type(stamp) is not int or stamp <= 0: raise SystemExit('信任时间戳异常，停止')
        if old is None or records != json.loads(content):
            permissions = approvals.stat().st_mode & 0o777 if old is not None else 0o600
            save(approvals, records, old, permissions)
        if state(path) != mcp_stamp or json.loads(approvals.read_bytes()).get(key) != stamp:
            raise SystemExit('信任记录回读校验失败，停止')
        print('TRUST_VERIFIED')
    except KeyboardInterrupt:
        if mode != 'sign-in': raise
        if sign_in_authorized:
            raise SystemExit('OpenAgent 已完成授权，配置核验被中断，停止；不重放换码请求') from None
        print('SIGN_IN_CANCELLED', flush=True)
        raise SystemExit('用户已中止 OpenAgent 登录流程，停止；不重放换码请求') from None
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        raise SystemExit(stage + '失败，停止；不输出凭据或服务端响应；已保存凭据时使用 resume 恢复，否则核对授权结果，不重放换码或刷新请求') from None
    finally:
        cleanup.close()

if __name__ == '__main__':
    main()
