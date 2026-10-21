# Install OpenAgent in WorkBuddy (REL)

This guide is only for WorkBuddy. Before running anything, confirm the actual client instead of trusting a copied prompt. If the platform does not match, do not run commands, register OAuth, or change configuration. Return to the [OpenAgent installation hub](https://oasn-ow.haimawan.com/plugin) and use the guide for the current client. If the client cannot be identified or is not listed, stop and ask the user.

Attachment uploads require Node.js 20+. The plugin includes the fixed COS Node.js SDK bundle in the run Skill’s `scripts/cos_sdk.cjs.gz`, installed alongside `scripts/cos_upload.cjs` and `scripts/cos_sdk.lock.json`. On first use, the script verifies the compressed and decompressed SHA-256 values offline and decompresses the bundle into `scripts/.cos-sdk/node_modules/<archive SHA-256>/cos_sdk.cjs`. Later uses verify and reuse the cache; a missing or damaged cache, or an updated bundle, triggers decompression automatically. The cache remains after exit. The current user must be able to write to `scripts/`. Upload checkpoint cleanup does not load the SDK. The plugin does not search for a host SDK, run `npm install`, or download dependencies. Stop and repair the plugin installation if installation files are missing or verification fails. Installation and OAuth scripts still require Python 3.9+.

The WorkBuddy Agent performs the steps; the user personally completes browser authorization. Confirm the actual OS first: use Bash on macOS and PowerShell on Windows; run only the matching branch. Run steps in order and stop on failure. Do not expose an authorization code, PKCE verifier, access token, or refresh token.

To migrate an existing REL installation, start again from step 1, register a new client in step 2, have the user authorize on the new domain, and run step 4 in `exchange` mode. The script accepts migration only from `https://oasn-pre.haimawan.com/mcp/v1/open-agent` to `https://oasn-ow.haimawan.com/mcp/v1/open-agent`, preserving other MCP servers, custom fields, and disabled state. Other environments and custom URLs remain conflicts. Credentials for the old domain cannot be used with `resume` or `refresh`; do not relabel their `resource` or reuse their tokens. Recovery applies only after new credentials have been saved. Trust uses the new origin; uninstall remains compatible with both REL URLs.

## Download mirrors

The installation Agent prefers `https://gitee.com/openagent-org/workbuddy-plugin.git`, with `https://github.com/openagent-org/workbuddy-plugin.git` as the fallback. Preserve an existing official source unless explicitly switching with `setup.py --source gitee|github`. The old website source is accepted only for migration.

Download installation scripts directly from `rel`. Use `https://gitee.com/openagent-org/workbuddy-plugin/raw/rel` for Gitee or `https://raw.githubusercontent.com/openagent-org/workbuddy-plugin/rel` for GitHub. When switching sources, replace the download base and `install_source` while preserving the file path.

Only DNS, connection, timeout, interrupted-transfer, or HTTP 5xx download failures allow one fallback after the original command ends. Do not switch sources for approval denials, certificate errors, HTTP 401/403/404/429/451, or digest, syntax, installation, or OAuth failures. Preserve the host's approval flow. Download to a private temporary file and execute it once after the download completes. Discard partial files when switching sources and retry only the failed download; do not join partial output or repeat code exchange, configuration, uninstall, or restart steps that have already run.

Native WorkBuddy downloads from `rel` or the default branch. Read back the official source and installed/cache versions, and verify the installation files. Switching sources must not change MCP configuration or repeat OAuth.

## 1. Prepare the local environment

At the start, say only `Installing OpenAgent…`. When the browser is open and user authorization is required, say only `Please sign in to OpenAgent in the opened page…`. Do not repeatedly narrate every step.

```bash
curl --version
git --version
python3 --version
```

Python 3.9 or newer and a previously launched WorkBuddy installation are required. The final response must use exactly one of the two-line templates in section 8, with no heading, list, code fence, or extra explanation.

## 2. Register an OAuth client and generate PKCE

Register a public OAuth client:

```bash
curl -s -X POST "https://oasn-ow.haimawan.com/owner-oauth/register" \
  -H "Content-Type: application/json" \
  -d '{
    "client_name": "workbuddy",
    "redirect_uris": ["http://127.0.0.1:52961/callback"],
    "grant_types": ["authorization_code", "refresh_token"],
    "response_types": ["code"],
    "token_endpoint_auth_method": "none",
    "scope": "agent.discover agent.invoke artifact.read"
  }'
```

The response must contain a non-empty `client_id`; otherwise stop. Use it as `<CLIENT_ID>` below. It is a public client identifier, not a Secret or Token.

Generate one PKCE pair:

```bash
python3 -c "
import secrets, hashlib, base64
verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode()
challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
print(f'VERIFIER={verifier}')
print(f'CHALLENGE={challenge}')
"
```

Use the same pair: `CHALLENGE` for authorization and `VERIFIER` for exchange. Do not mix values from different attempts or paste them into the final response.

## 3. Complete browser authorization

Replace `<CLIENT_ID>` and `<CHALLENGE>`, then run the command once. It opens the browser, listens on local port `52961`, validates `state`, and prints `CODE` only after the user signs in and approves access.

```bash
python3 -c "
import http.server, socketserver, urllib.parse, webbrowser, secrets
state = secrets.token_urlsafe(32)
URL = 'https://oasn-ow.haimawan.com/owner-oauth/authorize?response_type=code&client_id=<CLIENT_ID>&code_challenge=<CHALLENGE>&code_challenge_method=S256&redirect_uri=http://127.0.0.1:52961/callback&scope=agent.discover+agent.invoke+artifact.read&resource=https://oasn-ow.haimawan.com/mcp/v1/open-agent&state=' + state
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
    print('Please sign in and approve access in the browser…')
    for _ in range(180):
        s.handle_request()
        if 'code' in captured: break
if not captured.get('code'): raise SystemExit('Authorization cancelled, timed out, or state mismatched; stopping')
print('CODE=' + captured['code'])
"
```

Cancellation, timeout, state mismatch, or user rejection ends the attempt. Do not automatically start another authorization flow.

## 4. Exchange the code, configure MCP, and register trust

Replace `CLIENT_ID`, `CODE`, and the matching `VERIFIER`. Keep `mode='exchange'` and run this as one tool call. The script published on `rel` exchanges the code internally, privately saves credentials, merges MCP configuration, initializes the MCP, and registers trust. Authorization values are passed through JSON on stdin, not command arguments. Do not read or print the saved credential file or MCP Authorization header.

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

Credentials and MCP configuration are stored separately in `~/.workbuddy/openagent-rel-oauth.json` and `~/.workbuddy/mcp.json` with POSIX mode `0600`. Other MCP servers, top-level fields, custom headers, and disabled state are preserved. Invalid JSON, invalid types, symlinks, or a same-name server from another source must fail before code exchange.

Continue only after both `MCP_VERIFIED` and `TRUST_VERIFIED`. Do not expose Tokens, response bodies, or exception details. If the Token was saved but a later configuration, initialization, or trust step failed, rerun the same downloaded program with `mode='resume'`; do not exchange the one-time code again. If exchange outcome is unknown or saving failed, stop and investigate instead of replaying the request.

`X-OASN-MCP-Legacy-SSE: enabled` permits WorkBuddy's legacy HTTP+SSE fallback while normal HTTP POST remains supported. It does not replace Bearer authentication. Trust is keyed by `SHA-256(URL.origin)::openagent` for the fixed origin `https://oasn-ow.haimawan.com`; it does not replace browser OAuth, host file approval, or connector enablement.

## 5. Refresh an expired Token

Only when OpenAgent is present and a request returns `Unauthorized` due to expired or failed authentication, change `mode='exchange'` in section 4 to `mode='refresh'` and run once. The program reads the private `client_id` and refresh token, saves the new credential, updates MCP configuration, verifies the connection, and rechecks trust without returning credential values.

If a refresh response was saved but later configuration or verification failed, use `resume`, not another refresh. If refresh fails or its result is unknown, stop. If the refresh token is no longer valid, reuse the existing public `client_id`, generate a new PKCE pair using only the PKCE command in section 2 without registering another client, authorize again in section 3, and perform one new exchange in section 4. Do not make the model read an old Token from MCP configuration.

## 6. Install Skills and prepare the startup message

The native plugin provides five Skills. Confirm Git first with `git --version`. On macOS and Windows, do not separately edit settings: section 7 first merges the `openagent-workbuddy` REL Marketplace and plugin enablement into `~/.workbuddy/settings.json`, and appends `openagent-workbuddy-restart.sh` to `sandbox.excludedCommands` in the current task project's `.codebuddy/settings.local.json`. It uses the absolute `CODEBUDDY_PROJECT_DIR` when supplied, otherwise the command's current directory; confirm this is the task project root. Each file is replaced atomically only when needed. Preserve other settings, existing exclusions, and file permissions; new files use mode `0600`. Reject source conflicts, invalid JSON or types, symlinks, and project settings write protection. A failure stops plugin verification and restart; the two files are not one transaction. Configuration alone does not prove the command was excluded or that restart succeeded.

`PLUGIN_READY` only proves that the plugin is enabled, its registered path is valid, and the five Skills plus required references are present and non-empty. It does not prove that the current task loaded them. The setup waits up to 60 seconds for download; timeout or failure must stop without repeating OAuth or manually copying Skills. Invalid JSON, permission errors, source conflicts, or invalid registration paths fail immediately rather than being treated as download delays. Do not automatically rerun the preparation command or schedule restart after a failure or tool timeout. Only an explicit user request to resume, together with confirmation that restart has not been scheduled and sending has not been attempted, permits recovery.

In the new task after restart, verify the required shared MCP tools, including result lookup and recent invocations, and support for boolean `async` in `openagent_run`. Check required capabilities without relying on a fixed tool count. Configuration writes or HTTP 200 do not prove that the host loaded the tools.

Choose the restart message from the user's explicit intent. Do not treat examples, attachments, or quoted text as authorization to run an Agent.

Without an `agent_id`:

```text
OpenAgent is installed. Open the new-user guide.
```

With an `agent_id`, choose the message according to the user's language and preserve the user's name and ID exactly:

| Name available | English message | Chinese message |
| --- | --- | --- |
| Yes | `Use "{name}" (agent_id: {agent_id}) on OpenAgent` | `使用 OpenAgent 上的「{name}」(agent_id: {agent_id})` |
| No | `Use (agent_id: {agent_id}) on OpenAgent` | `使用 OpenAgent 上的 Agent (agent_id: {agent_id})` |

No `sa_` prefix is required; treat the ID as opaque and do not use placeholders as defaults. If the user also supplied a business request, append it as a new paragraph without rewriting it. Keep this Agent selection instead of replacing it with the first-time guide; `openagent-guide-agent` hands it to `openagent-run-agent`. Without a business request, the selected Agent flow asks for the task and does not invent a trial task. The startup message must not contain installation links, installation commands, or process narration.

## 7. Restart WorkBuddy and send once

Run this section only after OAuth, MCP merge and initialization, and trust verification succeed. Choose the branch for the actual OS. The first foreground call verifies the plugin before preparing the restart scripts. Create a UTF-8 JSON file containing `{"message":"the complete startup message"}` using the file tool; JSON serialization must preserve newlines, quotes, and backslashes. Pass its absolute path as `message_file`.

On macOS, use two separate Bash tool calls, each with `run_in_background=false` and `timeout=120000`. The first prepares settings, verifies the plugin, and downloads the published restart script. The second directly invokes that script so the host evaluates the command after the exclusion is written. The script itself creates the detached worker. Do not combine the calls, use host background mode, disable sandbox protections, or execute workspace copies of these scripts.

If the restart script download fails after setup has run, follow "Download mirrors" for that file and continue only the remaining steps. Do not rerun setup, OAuth, or the entire preparation command.

登记所选官方源 `rel`；旧官网源可迁移，未知同名源停止。未传 `--source` 保留已有官方源，新装默认 Gitee。须回读匹配的宿主来源，安装与缓存版本一致且至少 `0.2.84`，才接受 `PLUGIN_READY`。旧源/缓存未刷新则等待；60 秒超时不作为换源依据，不清缓存、不报告完成。原生下载明确发生可回退网络错误时，确认已结束且未安排重启，只恢复来源和未完成下载，不重复 OAuth。

```bash
(
  set -eu
  install_source='gitee'
  install_base='https://gitee.com/openagent-org/workbuddy-plugin/raw/rel'
  message_file='<ABSOLUTE_PATH_TO_STARTUP_MESSAGE_JSON>'
  chmod 600 "$message_file"
  restart_dir="$(mktemp -d "$HOME/.workbuddy/.openagent-restart.XXXXXX")"
  trap 'rm -f -- "$restart_dir/setup.py" "$restart_dir/openagent-workbuddy-restart.sh"; rmdir -- "$restart_dir"' EXIT
  curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' \
    "$install_base/scripts/openagent-workbuddy-setup.py" \
    -o "$restart_dir/setup.py"
  python3 "$restart_dir/setup.py" --source "$install_source"
# restart
  curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' \
    "$install_base/scripts/openagent-workbuddy-restart.sh" \
    -o "$restart_dir/openagent-workbuddy-restart.sh"
  sh -n "$restart_dir/openagent-workbuddy-restart.sh"
  chmod 700 "$restart_dir/openagent-workbuddy-restart.sh"
  restart_script="$HOME/.workbuddy/openagent-workbuddy-restart.sh"
  test ! -L "$restart_script" && test ! -d "$restart_script"
  mv -f "$restart_dir/openagent-workbuddy-restart.sh" "$restart_script"
  printf 'RESTART_SCRIPT_READY=%s\n' "$restart_script"
)
```

Only after the first call returns both `PLUGIN_READY` and `RESTART_SCRIPT_READY`, replace the script placeholder below with the absolute path printed by this run. Reuse the same startup-message JSON path. The second Bash call must contain only this direct invocation: do not prepend `sh`, wrap it in a compound command, or rename the script. The host must evaluate it under the current task project's exclusion settings. If the host still runs it in the sandbox or requires native approval, follow that outcome without forcing a bypass. Keep `--require-existing-trust`; an older script that rejects it must stop rather than fall back to reading MCP configuration.

```bash
"<RESTART_SCRIPT_READY_ABSOLUTE_PATH>" install --require-existing-trust --wait-for-turn --message-file "<ABSOLUTE_PATH_TO_STARTUP_MESSAGE_JSON>"
```

The foreground verifies existing fixed-source trust without rereading MCP content, saves the private request, and starts an independent Python worker. After the current task reaches `completed`, the worker exits old WorkBuddy processes, launches a new instance, waits for CDP and `globalThis.wb`, enables OpenAgent, creates a new task, fills the exact message with `wb.conversations.prepareInput()`, and calls `store.api.send()` once. It does not simulate keyboard or mouse input and does not guess from historical titles.

A worker PID proves only process creation. Acceptance requires old-process exit, new-instance launch, exactly one complete startup message in the new task, and the required tools loaded. If sending is complete or unknown, inspect the new task before any retry. Never repeat OAuth, restart, or message delivery automatically. If the automated flow cannot be used and delivery is confirmed not attempted, ask the user to fully quit and reopen WorkBuddy, create a new task, and send the same message manually.

### Windows: first foreground PowerShell call

Use two separate foreground PowerShell tool calls, each with a 120000 ms timeout; do not use host background mode. Create the UTF-8 startup-message JSON with the file tool first, preserving the complete message and business request. Pass only its absolute path in the second call; do not place its content in arguments or logs. Download and run the published setup first. Only after it returns `PLUGIN_READY`, download the Windows Python restart script, check its syntax, and save it under the current user's `~/.workbuddy` without running a restart.

```powershell
$ErrorActionPreference = 'Stop'
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$installSource = 'gitee'
$installBase = 'https://gitee.com/openagent-org/workbuddy-plugin/raw/rel'
$targetDir = Join-Path $HOME '.workbuddy'
$restartDir = Join-Path ([IO.Path]::GetTempPath()) ('openagent-restart-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $restartDir | Out-Null
try {
  $setup = Join-Path $restartDir 'setup.py'
  curl.exe --fail --location --silent --show-error --proto '=https' --proto-redir '=https' "$installBase/scripts/openagent-workbuddy-setup.py" -o $setup
  if ($LASTEXITCODE -ne 0) { throw 'Setup download failed' }
  $result = & python3 $setup --source $installSource
  $code = $LASTEXITCODE
  $result | Write-Output
  if ($code -ne 0 -or $result -notcontains 'PLUGIN_READY') { throw 'Plugin verification failed' }
  $download = Join-Path $restartDir 'openagent-workbuddy-restart.py'
  curl.exe --fail --location --silent --show-error --proto '=https' --proto-redir '=https' "$installBase/scripts/openagent-workbuddy-restart.py" -o $download
  if ($LASTEXITCODE -ne 0) { throw 'Restart script download failed' }
  & python3 -c "import ast,sys; from pathlib import Path; ast.parse(Path(sys.argv[1]).read_text(encoding='utf-8-sig'))" $download
  if ($LASTEXITCODE -ne 0) { throw 'Python syntax check failed' }
  $destination = Join-Path $targetDir 'openagent-workbuddy-restart.py'
  if (Test-Path -LiteralPath $destination) {
    $item = Get-Item -LiteralPath $destination -Force
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) { throw 'Invalid script destination' }
  }
  Move-Item -LiteralPath $download -Destination $destination -Force
  Write-Output ('RESTART_SCRIPT_READY=' + $destination)
} finally {
  Remove-Item -LiteralPath $restartDir -Recurse -Force
}
```

For a failed download, apply "Download mirrors" only to that file and continue the unexecuted steps. Preserve the saved restart script; do not rerun setup, OAuth, or the entire preparation command. Stop on syntax, configuration, or permission failures. Setup retains its existing `.sh` exclusion; Windows does not depend on it. Do not add broad `python`, `python3`, or `powershell` exclusions, use `ExecutionPolicy Bypass`, disable security settings, or bypass approval. Follow native host approval and stop if denied.

### Windows: second foreground PowerShell call

Proceed only after `PLUGIN_READY` and `RESTART_SCRIPT_READY`. Use the Python 3.9+ checked during preparation, replace both absolute paths, and run only:

```powershell
python3 '<RESTART_SCRIPT_READY_ABSOLUTE_PATH>' install --require-existing-trust --wait-for-turn --message-file '<ABSOLUTE_PATH_TO_STARTUP_MESSAGE_JSON>'
```

`--wait-for-turn` requires the current `CODEBUDDY_SESSION_ID`; if absent, stop instead of restarting immediately. The worker waits for `completed` before exiting old processes. It must break away from the host Job; failure stops without falling back to ordinary detached launch. This does not remove all command sandbox restrictions; native approval still applies. Discover the application executable from its running process rather than a fixed user directory or installation drive. Send the complete message once through CDP after restart. If the enable API is unavailable, attempt sending only when local configuration explicitly confirms the connector is not disabled; verify its connection and required tools in the new task. Actual Windows process termination, relaunch, and message injection have not been tested on a Windows host; offline checks do not prove those stages succeeded. Apply the acceptance and failure rules above; never resend when the result is unknown.

For Windows OAuth commands, use `curl.exe`, UTF-8 output, a unique system temporary directory, exit-code checks, and `try/finally` cleanup. Feed exchange JSON through a single-quoted here-string to the Python script published on `rel`. Do not run macOS `chmod`, `mktemp`, or Bash restart commands.

## 8. Report completion or failure

Only after OAuth, MCP merge and initialization, trust readback, and `PLUGIN_READY` all succeed may configuration be reported as complete. Tools are verified in the new task after restart; configuration completion must not be reported as successful host loading.

When scheduling on the selected platform returns the independent Python worker creation log, the final response must contain exactly these two plain-text lines:

```text
OpenAgent installation and configuration are complete.
WorkBuddy will restart after the current task completes and will send the startup message automatically.
```

This reports scheduling only; it does not claim that restart, send, or tool loading has already succeeded.

If configuration completed but the automatic flow was not executed and message delivery is confirmed not attempted, use:

```text
OpenAgent installation and configuration are complete.
{brief reason automation was not run}; fully quit and restart WorkBuddy, create a new task, and send: {startup message}
```

Replace every placeholder. If the business request must be included, add only `; also include your original business request` to the second line rather than repeating its content.

For cancellation, authorization timeout, failure, or another pending issue, use exactly:

```text
OpenAgent installation is not complete: {brief reason}.
Next step: {the currently actionable step}.
```

Do not disclose sensitive values, hide a failure, or append a checklist, summary, or notes after the two lines.
