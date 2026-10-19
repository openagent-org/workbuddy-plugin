# OpenAgent runtime sign-in

## When to use

Use this only after an OpenAgent Tool or the Host explicitly reports missing or expired OpenAgent authentication, such as `MCP_AUTH_REQUIRED` or `MCP_TOKEN_INVALID`. A bare HTTP status, missing tool, insufficient scope, business error, or network failure is not enough. Do not check login before normal calls. Anonymous search, guide, and selection calls stay anonymous unless their supplied credentials are explicitly rejected.

This takes priority over the caller's failure, fallback, and completion rules. Headless or delegated calls return the trusted authentication failure to their caller; that caller owns the single login flow and user messages. This does not handle App-only tools.

## Flow and messages

Use `display_locale`; if unset, choose explicit preference > trusted Host locale > conversation language > `en-US`. Show only the matching column, without workflow labels.

| State | zh-CN | en-US |
| --- | --- | --- |
| Starting login | 需要登录 OpenAgent 才能继续。正在打开登录页面… | Please sign in to OpenAgent to continue. Opening the sign-in page… |
| Page opened, still waiting | 请在打开的页面中登录 OpenAgent… | Please sign in to OpenAgent in the page that opened… |
| Authorization confirmed | 已登录 OpenAgent | Signed in to OpenAgent |
| Timed out | 还未完成登录。回复“继续登录”，我会重新打开登录页面。 | Sign-in is not complete yet. Reply ‘continue sign-in’ and I will reopen the sign-in page. |

1. Use the login path below for the actual failing connection. If the Host or this conversation already has a login in progress, wait using the same process or session handle; do not start another or repeat its messages, even if the user says "continue sign-in" while it is pending. If the previous attempt's state cannot be confirmed, report that uncertainty and do not start another attempt.
2. Send the starting message immediately before launching login once. Keep and wait on the same process. Only the `--mode sign-in` script below may open the OAuth page. Do not additionally use `open`, `start`, `Start-Process`, `xdg-open`, browser tools, or an in-app browser to open it. A printed OAuth URL alone does not prove opening and must never be used to open another page. Show the waiting message only after confirmed opening and while authorization is pending. These opening restrictions apply only to OAuth pages; normal discovery, selection, and result-page handoffs are unchanged.
3. Confirm this attempt's authorization callback and successful token exchange, then show the success message and perform the configuration check below. Report any verification failure separately. Configuration verification is not business success.
4. Cancellation, denial, trusted page-closure reports, opening failure, login failure, or authorization timeout ends the attempt without automatic retry. A short tool wait, a still-running result, or no new output is not an OAuth timeout; keep waiting on the same attempt. Use the fixed timeout message only when the login entry explicitly reports authorization timeout. If page closure is not observable, wait for the attempt's bounded outcome instead of claiming closure. Start one fresh attempt only after confirming the previous process or session has ended and the user explicitly asks to continue sign-in again. Never terminate or abandon the old attempt merely to enable a retry.

## Login

使用当前 WorkBuddy 宿主的本地命令执行器。下载优先使用 `https://gitee.com/openagent-org/workbuddy-plugin.git`，备用为 `https://github.com/openagent-org/workbuddy-plugin.git`。先用 `git ls-remote --exit-code <所选仓库> refs/heads/rel` 保存完整 40 位 `install_sha`；首源在解析 SHA 前发生可回退网络错误时，备用源可确定本次初始 SHA。取得 SHA 后不得重新解析备用源的 rel。下载路径固定为 `scripts/openagent-workbuddy-exchange.py`：首源 `https://gitee.com/openagent-org/workbuddy-plugin/raw/<INSTALL_SHA>/scripts/openagent-workbuddy-exchange.py`，备用 `https://raw.githubusercontent.com/openagent-org/workbuddy-plugin/<INSTALL_SHA>/scripts/openagent-workbuddy-exchange.py`，两次沿用相同完整 SHA 和路径。

使用 `curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https'`（Windows 使用 `curl.exe`）完整下载到私有临时目录；仅 DNS、连接、超时、传输中断或 HTTP 5xx 可在原命令结束后切到备用源一次。权限或审批拒绝、证书校验、HTTP 401/403/404/429/451、摘要或语法校验错误不换源；备用失败停止，不来回循环。丢弃失败下载的残片；完整下载成功后只运行一次 `python3 "<downloaded-script>" --mode sign-in`，退出后只清理该临时目录。脚本已启动、登录取消、OAuth/MCP 或配置失败均不得换源重跑登录；保持前述单次登录和已有会话等待规则。

If curl fails, request one retry outside the sandbox using the exact
same command (Codex: sandbox_permissions="require_escalated",
with a justification).
该审批规则仅处理同一下载命令；审批拒绝不得换源，批准后仍仅在上述网络错误时切换一次镜像。

On success, use the response; on execution failure, use the existing
fallback. If approval is denied, continue without the manual.

Count these steps as one loading attempt. Allow required approval prompts.


The script handles registration, PKCE, credentials, and the existing REL MCP configuration internally. Do not supply or read tokens. It requires an existing OpenAgent REL connection; other environments or missing configuration stop with an explanation.

- `SIGN_IN_OPENED`: the page was opened; show the waiting message only if authorization is still pending.
- `SIGN_IN_AUTHORIZED`: this attempt's callback, token exchange, and credential save succeeded; show the success message.
- `SIGN_IN_CANCELLED` / `SIGN_IN_TIMED_OUT`: stop and use the corresponding outcome above.
- `MCP_VERIFIED` and `TRUST_VERIFIED`: the script's configuration and connection checks passed. These do not prove that WorkBuddy has reloaded its active connection. If either check fails, report it and stop; do not automatically rerun sign-in, refresh, or resume.

Do not run the installer, settings, or restart_send workflow. Leave reloading the active connection to the Host's supported connection handling.
