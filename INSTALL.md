# OpenAgent WorkBuddy 安装指引（REL）

仅适用于 WorkBuddy。执行前确认当前实际客户端；若不匹配，不执行本文步骤，改用 [安装汇总页](https://openagent.org/plugin) 中的对应指南。无法确认客户端或没有对应指南时，停止并询问用户。

由 WorkBuddy Agent 执行，用户本人完成浏览器授权。第 4 步同次调用下载执行 rel 已发布的脚本；macOS 的设置与插件核验先在一次 Bash 完成，再由下一次 Bash 直接调用 rel 已发布的重启脚本。

Windows 使用 WorkBuddy 原生 PowerShell 工具。执行 `openagent-workbuddy-exchange.py`、`openagent-workbuddy-prepare.ps1`、`openagent-workbuddy-setup.py` 和 `openagent-workbuddy-restart.py` 时，每次工具调用设置 `dangerouslyDisableSandbox=true`、`run_in_background=false`、`timeout=120000`（毫秒），申请写入用户安装配置或重启应用所需的沙箱外权限。这些是与 `command` 同级的工具参数，不是脚本参数，也不使用 Codex 的 `sandbox_permissions`。参数仅提出申请，审批及实际执行方式以宿主结果为准；参数不可用、审批拒绝或超时、仍受沙箱拦截时停止，不关闭安全设置或换入口重试。不先普通执行这些脚本再重放；工具返回未完成任务时只等待原调用。Windows 跳过 macOS 专用 Bash 步骤，使用下方 PowerShell 分支。

Windows 与 macOS 使用相同的下载镜像规则：优先 Gitee，保留已有官方来源；仅网络下载失败时切换另一官方源一次。Windows 使用下方的只读预检和原生编辑流程。本指南依赖新增的 `scripts/openagent-workbuddy-prepare.sh` 和 `scripts/openagent-workbuddy-prepare.ps1`；须先随配套脚本发布到 `rel`，再发布引用它们的网页。

## 用户可见输出

实际执行下列步骤。开始只说“正在安装 OpenAgent…”，浏览器已打开且需要用户授权时只说“请在打开的页面中登录 OpenAgent…”。不重复提醒或逐步播报。

最终回复只按“完成报告”输出两行纯文本，无标题、列表、代码块或补充。返回值只供衔接验证；不复述协议版本、路径、权限、工具清单、scope、Token 有效期或刷新说明。宿主展示的工具调用和日志不受本文回复约束。

## 下载镜像

安装 Agent 选源：`https://gitee.com/openagent-org/workbuddy-plugin.git`，备用 `https://github.com/openagent-org/workbuddy-plugin.git`。保留已有官方源，`setup.py --source gitee|github` 才显式切换。

安装脚本统一从 `rel` 下载。Gitee 基址为 `https://gitee.com/openagent-org/workbuddy-plugin/raw/rel`，GitHub 基址为 `https://raw.githubusercontent.com/openagent-org/workbuddy-plugin/rel`。切换来源时替换下载基址和 `install_source`，保留文件路径。

仅 DNS、连接、超时、传输中断、HTTP 5xx 可在原命令结束后切备用一次。审批拒绝、证书错误、401/403/404/429/451、摘要/语法/安装/OAuth 失败不换源；保留原命令授权流程，不绕过审批。下载私有临时文件完整后执行一次；换源丢弃残片，只补失败下载，不拼接输出或重跑已执行的换码、配置、卸载、重启。

原生 WorkBuddy 按 `rel`/默认分支下载。回读官方来源、安装/缓存版本并核验安装文件。切源不改 MCP、不重复 OAuth。

## 准备

```bash
curl --version
git --version
python3 --version
```

安装需要 Python 3.9+ 和已运行过的 WorkBuddy；附件上传需要 Node.js 20+。上传依赖已随插件提供，无需另外安装。顺序执行，失败停止报告。前三步返回注册信息、PKCE 和授权码，第 4 步内部处理 Token；回复不复述授权码、VERIFIER 或 Token。

Windows 执行前四步时，使用 `curl.exe`，curl 续行改用反引号，先设置 `$OutputEncoding = [System.Text.UTF8Encoding]::new($false)`；Python `-c` 段原样执行。第 4 步在唯一系统临时目录下载同一 `rel` 脚本，用单引号 here-string 将 JSON 管道输入 `python3 <脚本路径> --mode exchange`（恢复/刷新改用 `resume`/`refresh`），用 `try/finally` 清理脚本和目录。每次原生命令后检查 `$LASTEXITCODE`，失败停止。

仅接受 `https://openagent.org/mcp/v1/open-agent` 的配置和凭据；其他来源停止覆盖，不能改写其 `resource` 或复用 Token。更新当前配置时保留其他 MCP、自定义字段和禁用状态；新凭据保存后的失败才按后文恢复。

## 1. 注册 OAuth 客户端（register）

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

响应必须包含非空 `client_id`，否则停止。将它填入授权步骤的 `<CLIENT_ID>`。`client_id` 是公开客户端标识，注册响应不含 Secret 或 Token。

## 2. 生成 PKCE（pkce）

```bash
python3 -c "
import secrets, hashlib, base64
verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode()
challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
print(f'VERIFIER={verifier}')
print(f'CHALLENGE={challenge}')
"
```

同组 `CHALLENGE` 用于授权，`VERIFIER` 用于换码；不混用新旧参数，回复不粘贴这些值。

## 3. 浏览器授权（authorize）

填入 `<CLIENT_ID>` 和 `<CHALLENGE>` 后执行。命令会打开浏览器，在本机 `52961` 端口接收回调并打印 `CODE`；用户本人登录并同意授权。

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

## 4. 交换 Token、配置 MCP、验证连接并登记信任（exchange）

填入本次 `CLIENT_ID`、`CODE` 和同组 `VERIFIER`，保持 `mode='exchange'`，执行一次工具调用：curl 下载 rel 已发布的脚本，Python 内部换 Token、私有保存、合并 MCP、初始化并登记信任。不将 Token 返回给模型，不使用 Edit 或拆分调用；授权参数通过标准输入 JSON 传入，不放入脚本参数。下载失败仅按“下载镜像”处理；脚本执行失败停止，不回退旧安装器或重放副作用；退出时清理临时脚本。新脚本须先发布到 rel，此入口才能使用。

凭据与 MCP 分别保存到 `~/.workbuddy/openagent-rel-oauth.json`、`~/.workbuddy/mcp.json`，POSIX 权限为 `0600`。安装 Agent 不读取、打印凭据文件或 MCP Authorization。保留其他 MCP、顶层配置、自定义字段、请求头及禁用状态；损坏 JSON、非法类型、符号链接或同名其他来源在换码前停止。私有临时文件原子替换，原文件变化时停止，不覆盖外部修改。

只有输出 `MCP_VERIFIED` 和 `TRUST_VERIFIED` 才能继续安装 Skills。不输出 Token、错误正文或异常详情。正数值 `expires_in` 决定到期时间；省略时内部读取 JWT 的未来数值 `exp`，认证仍由 MCP 服务完成。非法或缺少有效到期信息时停止，不猜测有效期。配置、初始化或信任失败且已输出 `TOKEN_SAVED` 时，改为 `mode='resume'` 执行，使用已保存凭据，不再次换码；换码结果未知或保存失败时停止核对，不重放一次性授权码。原生宿主权限审批保持。

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

`X-OASN-MCP-Legacy-SSE: enabled` 允许 WorkBuddy 代理降级时使用旧 HTTP+SSE；普通 HTTP POST 仍走现有协议。此标识不替代 Bearer 认证，也不影响 `text-compatible` 输出设置。服务端需先在全部 Access 节点部署兼容能力，再更新 WorkBuddy 配置。

脚本仅验证 `initialize` 的协议版本与能力，支持 JSON/SSE；信任及插件核验通过后按 restart_send 收尾，工具发现与验收由重启后的 WorkBuddy 新任务完成，不统计或展示工具总数。

## 连接器信任已在第 4 步完成

第 4 步初始化成功后，以内存中已校验的固定来源合并 `~/.workbuddy/mcp-approvals.json`；不另执行 trust 或读取 MCP 正文。登记前后仅用设备、inode、大小、纳秒修改时间检测 MCP 变化，变化停止；不替代内容或认证验证。

信任键为 `SHA-256(URL.origin)::openagent`，固定来源 `https://openagent.org`，不含 Token、路径或请求头。保留其他记录、已有正整数时间戳及权限，新建为 `0600`；空白文件按空记录合并，损坏 JSON、非法字段或符号链接停止。原子写入后仅回读信任记录，成功输出 `TRUST_VERIFIED`；失败用 resume，不重复 OAuth。

此记录不替代浏览器 OAuth、宿主文件审批或连接器启用；不要求回复“已信任”。已有 disabled 保持；缓存加载须按文末重启后在新任务验证。

## Token 过期时刷新（refresh）

如果 OpenAgent 已出现，但请求返回 `Unauthorized`，确认 Token 过期或认证失败后，将第 4 步下载执行命令的 `mode='exchange'` 改为 `mode='refresh'`，执行一次。程序内部读取私有凭据中的 `client_id` 和 `refresh_token`，刷新、保存最新凭据、更新 MCP 并验证连接；不需要模型填入或读取 Token，也不输出凭据。普通业务失败不刷新 Token。

刷新响应已成功保存、配置或验证失败时使用 `'resume'` 恢复，不再次刷新。刷新失败或结果未知时停止，不重复发送刷新请求。如果 Refresh Token 已失效，使用原公开 `client_id` 从第 2 步重新授权，再以 `'exchange'` 完成第 4 步。旧安装没有私有凭据文件时重新授权，不让模型从 MCP 配置读取旧 Token。

成功后同程序已核验信任记录，再按 restart_send 重启 WorkBuddy；工具加载与新任务验收要求不变。

## 安装 Skills 并开始使用（settings）

五个 Skills 由原生插件获取；先用 `git --version` 确认 Git。macOS 不单独执行本节：restart_send 的 settings 阶段合并 `~/.workbuddy/settings.json` 中的市场和插件启用，同时在当前任务项目的 `.codebuddy/settings.local.json` 中将 `openagent-workbuddy-restart.sh` 追加到 `sandbox.excludedCommands`。优先使用宿主提供的绝对路径 `CODEBUDDY_PROJECT_DIR`，否则使用命令当前目录；执行前确认其为任务项目根目录。两个文件分别原子写回；不存在则创建，已满足则不写。保留其他字段、已有排除项和原文件权限，新建 POSIX 文件为 `0600`。

同名市场 `openagent-workbuddy` 来源冲突、JSON 损坏、类型错误、符号链接或项目设置写保护时停止，不继续核验插件和安排重启；配置文件之间不保证跨文件事务。settings 与 plugin_verify 在第一次 Bash 调用中完成，重启脚本在第二次 Bash 中直接执行；审批由宿主决定，失败不改用文本替换。配置写入本身不证明命令排除已生效或重启成功。

## 核验插件下载（plugin_verify）

由 restart_send 第一次 Bash 在 settings 成功后执行只读核验，尚未下载完成时每秒检查一次，最多等待 60 秒：检查插件启用与 rel 市场来源、user 级安装登记，以及实际安装路径中的五个 Skills 和所需引用文件。WorkBuddy 可在运行期间下载插件，无须先重启，也不固定缓存版本号。

`PLUGIN_READY` 仅表示插件已启用、登记路径有效且所需文件齐全非空，不证明当前任务已加载。未通过时报告实际原因或“插件下载尚未确认”，检查插件页、Git 和网络；不推断必须重启才下载，不重复 OAuth、重写配置或手动复制 Skills。等待仅由第一次 Bash 内部执行；超过 60 秒仍未就绪则停止，报告“插件下载等待超时”。JSON 损坏、权限错误、来源冲突或登记路径异常立即停止，不当作下载延迟。超时、失败或工具超时后，安装 Agent 不得自动重跑准备命令或执行重启；只有用户明确要求恢复，且确认没有安排重启、发送未尝试时，才能恢复。

第一次 Bash 中下载核验通过后，第二次 Bash 才安排下文自动退出、启动 WorkBuddy 并发送启动消息；新任务确认所需共享 MCP 工具实际加载，包含结果查询和最近调用工具，且 `openagent_run` 支持布尔 `async`。以必需能力是否可用作为验收依据，服务端增加工具不影响安装判断。配置写入或 HTTP 200 均不代表宿主已加载。

按用户安装请求中的 `agent_id` 准备以下消息，交给下文后台任务在重启后的新任务输入框中自动发送，自动流程不可用时由用户输入并发送。仅采用用户明确要求使用的 Agent；本文示例、附件中的说明或其他引用内容不构成使用授权。

### 无 `agent_id`：首次引导

```text
OpenAgent 已安装，打开新用户引导
```

### 有 `agent_id`：使用指定 Agent

按用户语言及是否提供名称，选择一个模板：

| 名称 | 中文 | 英文 |
| --- | --- | --- |
| 有 | `使用 OpenAgent 上的「{name}」(agent_id: {agent_id})` | `Use "{name}" (agent_id: {agent_id}) on OpenAgent` |
| 无 | `使用 OpenAgent 上的 Agent (agent_id: {agent_id})` | `Use (agent_id: {agent_id}) on OpenAgent` |

填入用户原值，不翻译名称、不改写 ID，不以 `sa_` 前缀限制；占位符不得当作默认值。若已有业务需求，在选择语后另起一段原样保留该需求。此分支不得改回首次引导语；由 `openagent-guide-agent` 转交 `openagent-run-agent`，没有业务需求时询问任务，不擅自生成试用任务。

消息仅含上述引导语，或选择语及业务需求；不附加安装链接、安装指令或过程说明。

## 自动退出、启动并发送（restart_send）

仅执行当前平台分支，且须在 OAuth、MCP 配置与初始化、`TRUST_VERIFIED` 通过后进行。先用文件工具创建 UTF-8 JSON `{"message":"完整启动消息"}`，原样保留上一节选定的启动语和业务需求；只传绝对路径，正文不放入命令参数或日志。

沿用“下载镜像”的本次官方源，只执行本次从 `rel` 下载的脚本，不使用工作区或历史副本。下方以 Gitee 为例；选择 GitHub 时，来源参数改为 `github`，下载基址改为 `https://raw.githubusercontent.com/openagent-org/workbuddy-plugin/rel`，后续准备沿用同一来源。

### macOS：1. 准备

使用两次独立 Bash 工具调用，每次设置 `run_in_background=false`、`timeout=120000`（毫秒）。第一次更新配置并核验插件，第二次让宿主按新配置判断重启命令；不得合并、启用宿主后台模式或设置 `dangerouslyDisableSandbox` 绕过授权。

将消息占位符替换为 JSON 的绝对路径，执行：

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

第一次调用成功且返回 `PLUGIN_READY` 和 `RESTART_SCRIPT_READY`，才在第二次 Bash 直接执行脚本。插件下载等待、超时和来源冲突按前文“核验插件下载”处理，不清缓存或自动重跑准备命令。

### macOS：2. 安排重启

脚本路径使用本次 `RESTART_SCRIPT_READY`，消息使用同一 JSON。第二次 Bash 只执行下方单条命令，不加 `sh`、包装命令或额外检查；文件名保持 `openagent-workbuddy-restart.sh`：

```bash
"<RESTART_SCRIPT_READY_ABSOLUTE_PATH>" install --require-existing-trust --wait-for-turn --message-file "<完整启动消息JSON绝对路径>"
```

命令成功并返回“已创建独立 Python 后台 PID=…”后，立即按“完成报告”结束当前任务，不轮询。后台等待本任务完成，再退出、启动 WorkBuddy 并发送一次完整消息。macOS 会强制退出相关进程，可能中断其他任务。

### Windows：1. 预检与按需编辑

沿用文首的 PowerShell 工具参数和原生审批。执行只读预检，记录本次 `PREPARE_SCRIPT_READY` 和 `SETUP_SCRIPT_READY` 的绝对路径；第 2 步复用这两个文件。预检或后续编辑失败时清理两者；清理被拒则报告残留并停止。

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

取得上述两个路径后，按 `SETUP_CHECK_EXIT` 和实际输出判断，不只看外层退出码：

| 预检结果 | 下一步 |
| --- | --- |
| `0` 且有 `PLUGIN_READY` | 跳过编辑，进入第 2 步。 |
| `1` 且仅报告 `CONFIG_UPDATE_REQUIRED=<当前用户 .workbuddy/settings.json 绝对路径>` | 宿主无拒绝、审批失败或其他异常时，才允许编辑。 |
| 其他结果 | 停止。 |

仅在需要编辑时，用原生 Read/Edit 合并下列两项目标：

- 先读取预检路径，只接受缺失的同名市场或 Gitee/GitHub 官方 git 来源（`ref=rel`）；未知来源、结构错误、重复键或无法唯一定位时停止。
- 已有文件只用 Edit，保留其他插件、市场和对象字段。只有原生读取/元信息确认文件不存在（不是无权读取），且写前仍不存在，才用 Write 创建下列最小 JSON；不能整份覆盖已有文件。
- 只改插件启用和市场来源，不改 MCP、信任、沙箱或项目配置，不输出完整 settings 或凭据。编辑失败即停止，不用 shell/Python 兜底或循环编辑。

选择 GitHub 时，将示例的 `source.url` 改为 `https://github.com/openagent-org/workbuddy-plugin.git`，与本次选源一致：

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

### Windows：2. 准备重启脚本

占位符替换为预检输出的两个绝对路径；路径中的单引号写成两个单引号（`'` → `''`），后续命令同样处理。`-Source` 沿用本次选源。此步只读核验配置并准备脚本，不安排重启；结束时清理本次 prepare、setup 和临时下载。

```powershell
$ErrorActionPreference = 'Stop'
$prepare = '<PREPARE_SCRIPT_READY_ABSOLUTE_PATH>'
try {
  & $prepare -Stage prepare -Source gitee -SetupScript '<SETUP_SCRIPT_READY_ABSOLUTE_PATH>'
} finally {
  Remove-Item -LiteralPath $prepare -Force
}
```

### Windows：3. 安排重启

仅第 2 步成功返回 `PLUGIN_READY`、`RESTART_SCRIPT_READY` 和 `RESTART_PYTHON_READY` 后执行。替换为本次输出的 Python、脚本及同一消息 JSON 的绝对路径，单独调用下方命令：

```powershell
& '<RESTART_PYTHON_READY_ABSOLUTE_PATH>' -X utf8 -B '<RESTART_SCRIPT_READY_ABSOLUTE_PATH>' install --scheduled --require-existing-trust --wait-for-turn --message-file '<完整启动消息JSON绝对路径>'
```

命令成功并返回 `TASK_NAME`、`SCHEDULED_WORKER_PID`、`RESULT_PATH` 后，立即按“完成报告”结束本轮，不轮询。后台等待当前任务完成，确认无其他活跃任务后才重启并发送一次；保留 `RESULT_PATH` 供后续排障。

### 验收与失败处理

创建后台 PID 或取得 Windows 回执只表示已安排，不能证明重启或发送成功。实际验收由重启后的新任务或后续排障完成：确认旧实例退出、新实例启动、只有一条完整启动消息，以及所需工具已加载。安排成功后不在当前任务继续验收。

- 参数不支持、任务上下文缺失、权限/审批拒绝、超时或实例变化时停止，按原生授权处理；不删参数、关闭安全设置或换入口重试。
- 下载失败按“下载镜像”只补失败文件和未执行步骤；不重跑已完成的 setup、配置编辑、OAuth 或整个准备命令。
- 已发送或结果未知时先检查本次结果和新任务，不再次粘贴、回车或执行 install。已重启则检查新任务与输入框，不再次重启。仅确认未发送且自动流程不可用时，才按“完成报告”指导用户手动恢复并发送同一完整消息。

后台自动清理其请求文件及 Windows 本次计划任务；macOS 日志保留在 `~/.workbuddy/logs/wb-relaunch.log`，Windows 保留 `RESULT_PATH`。不要同时安排多次收尾。

## 新任务排障

若新任务没有 OpenAgent 工具，检查 `~/.workbuddy/mcp.json` 中 HTTP `openagent` 是否启用，URL 和请求头是否与第 4 步一致；连接验证使用 `resume`。沿用前文凭据与恢复规则，不为验收调用业务 Agent。

## 完成报告

按实际状态选择模板，仅输出两行纯文本，不留空行或追加说明。填实占位符，不输出敏感信息。配置完成须通过 OAuth、MCP 合并与初始化、信任回读及 `PLUGIN_READY`；工具加载由重启后的新任务核验。

配置完成且 restart_send 已按对应平台回执确认安排重启时：

```text
OpenAgent 安装配置已完成。
已安排当前任务完成后重启 WorkBuddy，并自动发送启动消息。
```

仅报告已安排，随后立即结束当前任务，不等待或宣称重启、发送及工具加载成功；实际验收见 restart_send。当前会话被重启取消时，不补报告或重复发送。

配置完成、自动流程不可用且确认未尝试发送时：

```text
OpenAgent 安装配置已完成。
{自动流程未执行的简短原因}；请完全退出并重启 WorkBuddy，新建任务并发送：{启动消息}
```

`{启动消息}` 使用前文选定的引导语或 Agent 选择语，名称和 ID 使用用户原值。已有业务需求时，第二行末尾仅追加“；并附上你原先的业务需求”；实际发送的完整消息仍原样保留业务需求。

已重启则第二行只提示检查新任务与输入框；发送结果未知时按 restart_send 检查，不再次重启或补发。

配置未完成、状态未知、失败、取消或授权超时等情况：

```text
OpenAgent 安装尚未完成：{简短原因}。
下一步：{当前可执行的操作}。
```
