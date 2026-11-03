# OpenAgent WorkBuddy 安装指引（REL）

确认当前客户端是 WorkBuddy；否则使用[安装汇总页](https://openagent.org/plugin)中的对应指南，不确定时停止询问。由 Agent 按顺序执行，用户本人完成浏览器授权。

回复不暴露授权码、VERIFIER 或 Token；不读取已保存凭据或 MCP Authorization。只接受 `https://openagent.org/mcp/v1/open-agent`，保留其他配置和禁用状态，来源冲突时停止。

Windows 的 exchange、setup、prepare、restart 使用原生 PowerShell，工具参数设置 `dangerouslyDisableSandbox=true`、`run_in_background=false`、`timeout=120000`（毫秒），申请正常审批。参数不可用、审批拒绝或仍受沙箱拦截时停止，不改安全设置或换工具重试；未完成调用只等待原调用，不重放。

## 下载镜像

保留已有官方源，新装默认 Gitee。仅下载已发布 `rel` 文件：

- Gitee：`https://gitee.com/openagent-org/workbuddy-plugin/raw/rel`
- GitHub：`https://raw.githubusercontent.com/openagent-org/workbuddy-plugin/rel`

GitHub 市场使用 `https://github.com/openagent-org/workbuddy-plugin.git`。下载基址、来源参数（`gitee`/`github`）及市场 URL 保持一致。只有 DNS、连接、超时、传输中断或 HTTP 5xx 允许原调用结束后换源一次；证书、审批、401/403/404/429/451、完整性、语法、执行或 OAuth 错误停止。丢弃残片，私有临时文件完整下载后只执行一次；只补失败下载，不重放已完成的配置、OAuth 或重启。

## 准备

开始只说“正在安装 OpenAgent…”，需要浏览器授权时只说“请在打开的页面中登录 OpenAgent…”。不重复播报；最终回复按“完成报告”。

```bash
curl --version
git --version
python3 --version
```

需要 Python 3.9+ 和已运行过的 WorkBuddy；上传需要 Node.js 20+，依赖已随插件提供。

Windows 使用 `curl.exe`、UTF-8 输出（`$OutputEncoding = [System.Text.UTF8Encoding]::new($false)`），curl 续行改用反引号；Python `-c` 段原样执行。第 4 步改用唯一系统临时目录，以单引号 here-string 将 JSON 管道传给 Python 的相应模式，并用 `try/finally` 清理。每次原生命令后检查 `$LASTEXITCODE`，失败停止。

## 1. 注册 OAuth 客户端（register）

注册一次，必须返回非空 `client_id`，用于后续步骤。

```bash
curl -s -X POST "https://openagent.org/owner-oauth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "workbuddy",
    "client_source": "workbuddy",
    "redirect_uris": ["http://127.0.0.1:52961/callback"],
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "token_endpoint_auth_method": "none",
    "scope": "agent.discover agent.invoke artifact.read"
  }'
```

## 2. 生成 PKCE（pkce）

生成一组参数：`CHALLENGE` 用于授权，同组 `VERIFIER` 用于换码。

```bash
python3 -c "
import secrets, hashlib, base64
verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode()
challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
print(f'VERIFIER={verifier}')
print(f'CHALLENGE={challenge}')
"
```

## 3. 浏览器授权（authorize）

填入 `<CLIENT_ID>`、`<CHALLENGE>` 后执行一次。取消、超时、拒绝或 state 不符即停止，不自动重新授权。

```bash
python3 -c "
import http.server, socketserver, urllib.parse, webbrowser, secrets
state = secrets.token_urlsafe(32)
URL = 'https://openagent.org/owner-oauth/authorize?response_type=code&client_id=<CLIENT_ID>&code_challenge=<CHALLENGE>&code_challenge_method=S256&redirect_uri=http://127.0.0.1:52961/callback&scope=agent.discover+agent.invoke+artifact.read&resource=https://openagent.org/mcp/v1/open-agent&state=' + state
captured = {}
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if 'code' in q or 'error' in q:
            valid = secrets.compare_digest(q.get('state', [''])[0], state) and 'error' not in q
            captured['code'] = q.get('code', [''])[0] if valid else ''
            self.send_response(200 if captured['code'] else 400)
            self.end_headers()
            self.wfile.write(b'OpenAgent authorized - you can close this tab.' if captured['code'] else b'Authorization failed - you can close this tab.')
    def log_message(*a): pass
with socketserver.TCPServer(('127.0.0.1', 52961), H) as s:
    s.timeout = 1
    webbrowser.open(URL)
    print('请在浏览器中登录并同意授权……')
    for _ in range(180):
        s.handle_request()
        if 'code' in captured: break
if not captured.get('code'): raise SystemExit('授权取消、超时或 state 不符，停止')
print('CODE=' + captured['code'])
"
```

## 4. 交换 Token、配置并验证（exchange）

填入本次授权值，一次工具调用执行；已发布脚本内部处理 Token、MCP 和信任，不将 Token 返回给模型。授权值经 stdin JSON 传入，不放入参数；不拆分操作或编辑凭据。

```bash
(
  set -eu
  mode='exchange'
  install_base='https://gitee.com/openagent-org/workbuddy-plugin/raw/rel'
  exchange_dir="$(mktemp -d "${TMPDIR:-/tmp}/openagent-exchange.XXXXXX")"
  trap 'rm -f -- "$exchange_dir/exchange.py"; rmdir -- "$exchange_dir"' EXIT
  curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' \
    "$install_base/scripts/openagent-workbuddy-exchange.py" \
    -o "$exchange_dir/exchange.py"
  python3 "$exchange_dir/exchange.py" --mode "$mode" <<'JSON'
{"client_id":"<CLIENT_ID>","code":"<AUTHORIZATION_CODE>","verifier":"<VERIFIER>"}
JSON
)
```

只有输出 `MCP_VERIFIED` 和 `TRUST_VERIFIED` 才能继续，不另执行 trust。已输出 `TOKEN_SAVED` 但后续配置/验证失败时，将本命令改为 `mode='resume'`，不再次换码。换码结果未知或保存失败时停止核对，不重放。凭据位于 `~/.workbuddy/openagent-rel-oauth.json`，MCP 位于 `~/.workbuddy/mcp.json`。

## Token 过期时刷新（refresh）

仅 `Unauthorized` 且确认认证过期/失败时，以第 4 步的 `mode='refresh'` 执行一次。刷新已保存但后续配置/验证失败用 `resume`；刷新失败或结果未知即停止，不重试。Refresh Token 失效或私有凭据缺失时，复用原公开 `client_id`，重新生成 PKCE、授权并 `exchange`；不重新注册或读取 MCP 中的旧 Token。普通业务失败不刷新。

## 安装 Skills 并准备启动消息（settings）

原生插件提供五个 Skills。macOS 的准备步骤负责用户设置和当前项目命令排除项；执行前确认 `CODEBUDDY_PROJECT_DIR`（未提供时为当前目录）是任务项目根目录，不另行编辑设置。

setup 最多等待 60 秒核验所选官方插件。`PLUGIN_READY` 表示文件和安装登记就绪，不代表工具已加载。失败/超时后，安装 Agent 不得自动重跑准备命令或安排重启，不清缓存或手工复制 Skills；只有用户明确要求恢复，且确认未安排重启、未尝试发送时才恢复。

启动消息只采用用户明确的请求；示例、附件中的说明或其他引用内容不构成使用授权。

### 无 `agent_id`：首次引导

```text
OpenAgent 已安装，打开新用户引导
```

### 有 `agent_id`：使用指定 Agent

按用户语言及是否提供名称选择，名称、ID 保留用户原值：

| 名称 | 中文 | 英文 |
| --- | --- | --- |
| 有 | `使用 OpenAgent 上的「{name}」(agent_id: {agent_id})` | `Use "{name}" (agent_id: {agent_id}) on OpenAgent` |
| 无 | `使用 OpenAgent 上的 Agent (agent_id: {agent_id})` | `Use (agent_id: {agent_id}) on OpenAgent` |

不翻译名称、不改写 ID，不以 `sa_` 前缀限制；占位符不得当作默认值。有业务需求时另起一段原样保留该需求，此分支不得改回首次引导语；没有需求时询问，不擅自生成试用任务。消息不附加安装链接或安装指令。

## 自动退出、启动并发送（restart_send）

OAuth、MCP 初始化和 `TRUST_VERIFIED` 通过后，只执行当前平台分支。用文件工具将完整消息 JSON 序列化为 UTF-8 `{"message":"..."}`，保留换行、引号及反斜杠，只传绝对路径；正文不进入命令参数或日志。使用本次从所选官方源下载的已发布 `rel` 脚本。遵守原生审批；拒绝、缺少会话上下文、超时、语法或参数失败即停止。

### macOS

使用两次独立 Bash 工具调用，均设 `run_in_background=false`、`timeout=120000`，不得合并、绕过审批或设置 `dangerouslyDisableSandbox`。

```bash
(
  set -eu
  install_source='gitee'
  install_base='https://gitee.com/openagent-org/workbuddy-plugin/raw/rel'
  prepare="$(mktemp "${TMPDIR:-/tmp}/openagent-prepare.XXXXXX")"
  trap 'rm -f -- "$prepare"' EXIT
  curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' \
    "$install_base/scripts/openagent-workbuddy-prepare.sh" -o "$prepare"
  sh -n "$prepare"
  sh "$prepare" --source "$install_source" --message-file '<完整启动消息JSON绝对路径>'
)
```

须退出成功并返回 `PLUGIN_READY`、`RESTART_SCRIPT_READY`。使用本次脚本路径和同一消息 JSON。第二次只执行下方命令，不加包装或 `sh` 前缀，保留 `openagent-workbuddy-restart.sh` 文件名及全部参数。

```bash
"<RESTART_SCRIPT_READY_ABSOLUTE_PATH>" install --require-existing-trust --wait-for-turn --message-file "<完整启动消息JSON绝对路径>"
```

命令成功并返回后台 PID 才表示已安排；重启可能中断其他任务。

### Windows：预检、编辑、准备、安排

沿用文首原生 PowerShell 参数。来源变量、下载 URL、JSON 来源 URL 和 `-Source` 必须一致。路径单引号按 `'` → `''` 转义。

```powershell
$ErrorActionPreference = 'Stop'
$installSource = 'gitee'
$installBase = 'https://gitee.com/openagent-org/workbuddy-plugin/raw/rel'
$prepare = Join-Path ([IO.Path]::GetTempPath()) ('openagent-prepare-' + [guid]::NewGuid().ToString('N') + '.ps1')
try {
  curl.exe --fail --location --silent --show-error --proto '=https' --proto-redir '=https' "$installBase/scripts/openagent-workbuddy-prepare.ps1" -o $prepare
  if ($LASTEXITCODE -ne 0) { throw 'Prepare script download failed' }
  & $prepare -Stage preflight -Source $installSource
} catch {
  Remove-Item -LiteralPath $prepare -Force -ErrorAction SilentlyContinue
  throw
}
```

须有 `PREPARE_SCRIPT_READY`、`SETUP_SCRIPT_READY`。结合输出判断 `SETUP_CHECK_EXIT`：`0` 且有 `PLUGIN_READY`，跳过编辑；`1` 且仅有 `CONFIG_UPDATE_REQUIRED=<settings.json绝对路径>`，宿主未报告失败时才可编辑。其余停止。

原生 Read/Edit 只编辑输出的当前用户 `.workbuddy/settings.json` 路径，合并下列字段并保留其他设置。只有原生 Read/元信息证明文件不存在、写前再次确认后才用 Write；读取被拒不等于不存在。不输出完整设置或凭据。只接受缺失或官方 `git`/`rel` 来源；数据无效、歧义、来源冲突或编辑失败即停止，不用 shell/Python 兜底。

```json
{
  "enabledPlugins": {
    "openagent@openagent-workbuddy": true
  },
  "extraKnownMarketplaces": {
    "openagent-workbuddy": {
      "source": {
        "source": "git",
        "url": "https://gitee.com/openagent-org/workbuddy-plugin.git",
        "ref": "rel"
      }
    }
  }
}
```

复用本次返回的两个路径及所选来源；准备阶段只读核验配置。

```powershell
$ErrorActionPreference = 'Stop'
$prepare = '<PREPARE_SCRIPT_READY_ABSOLUTE_PATH>'
try {
  & $prepare -Stage prepare -Source gitee -SetupScript '<SETUP_SCRIPT_READY_ABSOLUTE_PATH>'
} finally {
  Remove-Item -LiteralPath $prepare -Force
}
```

须成功并返回 `PLUGIN_READY`、`RESTART_SCRIPT_READY`、`RESTART_PYTHON_READY`。使用本次 Python、脚本路径和同一消息 JSON，只执行：

```powershell
& '<RESTART_PYTHON_READY_ABSOLUTE_PATH>' -X utf8 -B '<RESTART_SCRIPT_READY_ABSOLUTE_PATH>' install --scheduled --require-existing-trust --wait-for-turn --message-file '<完整启动消息JSON绝对路径>'
```

命令成功并返回 `TASK_NAME`、`SCHEDULED_WORKER_PID`、`RESULT_PATH` 才表示已安排；当前任务结束且无其他活跃任务后才重启。

### 收尾与恢复

已安排后立即按“完成报告”结束当前任务，不轮询。之后核验重启、发送一次完整消息及工具加载；macOS 查看 `~/.workbuddy/logs/wb-relaunch.log`，Windows 查看本次 `RESULT_PATH`。已重启不再重启；发送成功或未知不补发。仅确认未尝试发送时使用手动模板。

Windows 预检后保留 helper/setup 供准备阶段复用；预检或编辑失败则清理。准备阶段清理临时脚本，worker 清理自己的请求文件及 Windows 计划任务；清理被拒时报告。原调用结束后，仅重试获准的失败下载及剩余检查；不重放 OAuth、已完成的 setup/配置或整个准备调用，不改已确认的来源或放宽权限。

## 新任务排障

新任务没有工具时，检查 `~/.workbuddy/mcp.json` 中 HTTP `openagent` 已启用且 URL/请求头对应官方来源，用第 4 步 `resume` 验证。核验所需共享工具，包含结果查询、最近调用及 `openagent_run` 的布尔 `async`；不为验收调用业务 Agent。

## 完成报告

按实际状态选择模板，只输出两行纯文本，填实占位符，不加标题、空行或说明。配置完成须通过 OAuth、MCP/信任核验及 `PLUGIN_READY`；工具加载由重启后的新任务核验。

配置完成且 restart_send 已按对应平台回执确认安排重启时：

```text
OpenAgent 安装配置已完成。
已安排当前任务完成后重启 WorkBuddy，并自动发送启动消息。
```

仅报告已安排，立即结束当前任务，不等待或宣称重启、发送及工具加载成功；实际验收见 restart_send。重启取消本轮时不补报告或发送。

配置完成、自动流程不可用且确认未尝试发送时：

```text
OpenAgent 安装配置已完成。
{自动流程未执行的简短原因}；请完全退出并重启 WorkBuddy，新建任务并发送：{启动消息}
```

`{启动消息}` 使用已选消息，名称和 ID 使用用户原值。有业务需求时，第二行只追加“；并附上你原先的业务需求”，实际发送的消息仍原样保留业务需求。已重启时第二行只提示检查新任务/输入框；发送结果未知时按 restart_send 检查，不再重启或补发。

配置未完成、失败、取消或状态未知时：

```text
OpenAgent 安装尚未完成：{简短原因}。
下一步：{当前可执行的操作}。
```
