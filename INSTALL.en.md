# Install OpenAgent in WorkBuddy (REL)

Install OpenAgent/MCP for this WorkBuddy user. Other hosts: use the [guide](https://openagent.org/plugin); stop if unsure.

Never expose codes/verifiers/tokens or read saved credentials/MCP Authorization. Only `https://openagent.org/mcp/v1/open-agent` is allowed. Preserve other settings/disabled states; stop on source conflicts.

## Download mirrors

Official `rel` sources: keep the current one if official; default to Gitee:

- Gitee: `https://gitee.com/openagent-org/workbuddy-plugin/raw/rel`
- GitHub: `https://raw.githubusercontent.com/openagent-org/workbuddy-plugin/rel`

GitHub marketplace: `https://github.com/openagent-org/workbuddy-plugin.git`. Match source, download base and marketplace. Switch once only for DNS/connection/timeout/interrupted-transfer/HTTP 5xx failures; all other errors stop the attempt. Discard partial files; download privately and fully before running once. Retry failed downloads only.

## Prepare

Say `Installing OpenAgent…`; report each stage once. Windows: `curl.exe` and Python 3.9+ (`python3` or `python`).

```bash
curl --version
git --version
python3 --version
```

Require Python 3.9+ and WorkBuddy launched before; uploads need Node.js 20+ with bundled dependencies.

Windows: UTF-8, backticks, Python `-c`. Step 4: pipe single-quoted here-string JSON to Python in a unique temp dir; clean up in `finally`. Stop on nonzero `$LASTEXITCODE`.

## 1. Register (register)

Register once; require nonempty `client_id`. macOS/Linux:

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

Windows: save that JSON to a unique UTF-8 temp file (no BOM). Insert its path below; delete it afterward.

```powershell
curl.exe -fsS https://openagent.org/owner-oauth/register -H 'Content-Type: application/json' --data-binary '@<JSON_FILE>'
```

## 2. PKCE (pkce)

Generate one pair: `CHALLENGE` for authorization, matching `VERIFIER` for exchange.

```bash
python3 -c "
import secrets, hashlib, base64
verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b'=').decode()
challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
print(f'VERIFIER={verifier}')
print(f'CHALLENGE={challenge}')
"
```

## 3. Authorize (authorize)

Run the browser-opening callback listener once; never ask for the URL. While waiting after `SIGN_IN_OPENED`, say “Please sign in to OpenAgent in the page that opened…” and await the same process.

On `SIGN_IN_TIMED_OUT` only, end with “Sign-in is not complete yet. Reply ‘continue sign-in’ and I will reopen the sign-in page.” That reply permits steps 2–3 once with the same client; no automatic retry.

```bash
python3 -c "
import http.server, socketserver, urllib.parse, webbrowser, secrets, time
state = secrets.token_urlsafe(32)
URL = 'https://openagent.org/owner-oauth/authorize?response_type=code&client_id=<CLIENT_ID>&code_challenge=<CHALLENGE>&code_challenge_method=S256&redirect_uri=http://127.0.0.1:52961/callback&scope=agent.discover+agent.invoke+artifact.read&resource=https://openagent.org/mcp/v1/open-agent&state=' + state
captured = {}
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query, keep_blank_values=True)
        if 'code' not in q and 'error' not in q: return
        valid_state = secrets.compare_digest(q.get('state', [''])[0].encode(), state.encode())
        captured['error'] = q.get('error', [''])[0] if valid_state else ''
        captured['code'] = q.get('code', [''])[0] if valid_state and 'error' not in q else ''
        self.send_response(200 if captured['code'] else 400)
        self.end_headers()
        self.wfile.write(b'OpenAgent authorized - you can close this tab.' if captured['code'] else b'Authorization failed - you can close this tab.')
    def log_message(*a): pass
with socketserver.TCPServer(('127.0.0.1', 52961), H) as s:
    s.timeout = 1
    if not webbrowser.open(URL): raise SystemExit('SIGN_IN_OPEN_FAILED')
    print('SIGN_IN_OPENED', flush=True)
    deadline = time.monotonic() + 180
    while not captured and time.monotonic() < deadline:
        s.handle_request()
if 'code' not in captured: raise SystemExit('SIGN_IN_TIMED_OUT')
if captured['error'] == 'access_denied': raise SystemExit('SIGN_IN_CANCELLED')
if captured['error']: raise SystemExit('SIGN_IN_FAILED')
if not captured['code']: raise SystemExit('SIGN_IN_INVALID_CALLBACK')
print('CODE=' + captured['code'])
"
```

## 4. Exchange and verify (exchange)

Pass JSON via stdin once; do not split calls or edit credentials.

Windows: approved native PowerShell only (`dangerouslyDisableSandbox=true`, `run_in_background=false`, `timeout=120000`). Await pending calls. Denied, unsupported or still sandboxed: stop; no security changes or tool-switch retries.

```bash
(
  set -eu
  mode='exchange'
  install_base='https://gitee.com/openagent-org/workbuddy-plugin/raw/rel'
  exchange_dir="$(mktemp -d "${TMPDIR:-/tmp}/openagent-exchange.XXXXXX")"
  trap 'rm -f -- "$exchange_dir/exchange.py" "$exchange_dir/openagent-workbuddy-token-proxy.py"; rmdir -- "$exchange_dir"' EXIT
  curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' \
    "$install_base/scripts/openagent-workbuddy-exchange.py" \
    -o "$exchange_dir/exchange.py"
  curl --fail --location --silent --show-error --proto '=https' --proto-redir '=https' \
    "$install_base/scripts/openagent-workbuddy-token-proxy.py" \
    -o "$exchange_dir/openagent-workbuddy-token-proxy.py"
  python3 "$exchange_dir/exchange.py" --mode "$mode" <<'JSON'
{"client_id":"<CLIENT_ID>","code":"<AUTHORIZATION_CODE>","verifier":"<VERIFIER>"}
JSON
)
```

On `TOKEN_SAVED`, say “Signed in to OpenAgent” once; later failures use `resume` (also migrates HTTP to stdio). Require `MCP_VERIFIED`/`TRUST_VERIFIED`; no separate trust step. Unknown exchange/failed save: stop and check; no replay. Credentials: `~/.workbuddy/openagent-rel-oauth.json`.

`TRUST_VERIFIED` must match the verified stdio launch configuration; an old HTTP-origin approval is insufficient. The installer only approves the managed OpenAgent proxy without custom `env` or `cwd`; unsupported process settings stop installation and remain unchanged. Restart only checks the current configuration and never adds trust.

Both scripts: same source.

## Refresh (refresh)

Confirmed auth failure (`Unauthorized`) only: step 4, `mode='refresh'`, once. If saved, use `resume` for later config/check failures. Failed/unknown refresh: stop, no retry. Invalid refresh token/missing credentials: reuse public `client_id`; repeat PKCE/authorize/exchange, not registration. No refresh for business failures.

## Skills and message (settings)

Five Skills are included. macOS preparation sets user settings/project exclusions; no separate edit. Confirm `CODEBUDDY_PROJECT_DIR` (default: cwd) is the task project root.

After writing configuration, setup explicitly runs the WorkBuddy bundled or PATH codebuddy CLI to add the selected official marketplace and install the user-scoped OpenAgent plugin. It first verifies that the official repository defaults to rel. Synchronization and the existing source, registration, file and dependency integrity checks share a 60-second deadline. A CLI failure or timeout stops the attempt without automatic replay. `PLUGIN_READY` means files/registration, not tool loading. Do not automatically rerun the preparation command or schedule restart after failure/timeout; no cache clearing/manual Skill copies. Only an explicit user request to resume permits recovery, with restart unscheduled and sending unattempted.

Only the user's request authorizes Agent selection; examples/attachments/quotes do not. Without `agent_id`:

```text
OpenAgent is installed. Open the new-user guide.
```

With `agent_id`, use the user's language and exact name/ID:

| Name available | English message | Chinese message |
| --- | --- | --- |
| Yes | `Use "{name}" (agent_id: {agent_id}) on OpenAgent` | `使用 OpenAgent 上的「{name}」(agent_id: {agent_id})` |
| No | `Use (agent_id: {agent_id}) on OpenAgent` | `使用 OpenAgent 上的 Agent (agent_id: {agent_id})` |

No `sa_` prefix is required; placeholders are not defaults. Keep the Agent; append the request verbatim in a new paragraph. If absent, ask; no invented trial or installation links/instructions.

## Restart and send once (restart_send)

After step 4, use your platform below. `--require-existing-trust` checks trust, never grants it. Save the exact message with a file tool as UTF-8 JSON `{"message":"..."}`; commands/logs get only its absolute path. Stop on denial, missing context, timeout or syntax/argument errors.

### macOS

Use two separate Bash calls with `run_in_background=false`, `timeout=120000`; never combine, bypass approval or set `dangerouslyDisableSandbox`.

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
  sh "$prepare" --source "$install_source" --message-file '<ABSOLUTE_PATH_TO_STARTUP_MESSAGE_JSON>'
)
```

Require exit success, `PLUGIN_READY` and `RESTART_SCRIPT_READY`. Reuse this run's path and JSON. Second call: exactly the command below; keep `openagent-workbuddy-restart.sh` and all arguments, with no wrapper or `sh` prefix.

```bash
"<RESTART_SCRIPT_READY_ABSOLUTE_PATH>" install --require-existing-trust --wait-for-turn --message-file "<ABSOLUTE_PATH_TO_STARTUP_MESSAGE_JSON>"
```

Success plus a background PID confirms scheduling. Restart may interrupt other tasks.

### Windows

Use step 4's PowerShell options. Match source variables, download/JSON URLs and `-Source`. Escape path quotes: `'` → `''`.

```powershell
$ErrorActionPreference = 'Stop'
$installSource = 'gitee'
$installBase = 'https://gitee.com/openagent-org/workbuddy-plugin/raw/rel'
$prepare = Join-Path ([IO.Path]::GetTempPath()) ('openagent-prepare-' + [guid]::NewGuid().ToString('N') + '.ps1')
try {
  curl.exe --fail --location --silent --show-error --proto '=https' --proto-redir '=https' "$installBase/scripts/openagent-workbuddy-prepare.ps1" -o $prepare
  if ($LASTEXITCODE -ne 0) { throw 'Prepare script download failed' }
  & $prepare -Stage check-and-prepare -Source $installSource
} finally {
  if (Test-Path -LiteralPath $prepare) { Remove-Item -LiteralPath $prepare -Force }
}
```

Ready configurations proceed directly to sync and preparation in this call. Edit only if the call succeeds with `SETUP_CHECK_EXIT=1` and the sole configuration finding `CONFIG_UPDATE_REQUIRED=<absolute settings.json path>`. Stop on other errors or timeouts.

Native Read/Edit only the returned current-user `.workbuddy/settings.json`; merge fields below, preserving others. Write requires native Read/metadata proof of absence, rechecked before writing; denial is not absence. Never print full settings/credentials. Sources: absent or official `git`/`rel` only. Invalid/ambiguous/conflicting data or edit errors: stop; no shell/Python fallback.

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

Only after the required edit succeeds, run the same PowerShell block once with the same source. It downloads fresh scripts, checks the configuration and prepares the restart. Stop if another edit is requested.

Require success and `PLUGIN_READY`/`RESTART_SCRIPT_READY`/`RESTART_PYTHON_READY`. Reuse this run's Python/script paths and JSON. Execute only:

```powershell
& '<RESTART_PYTHON_READY_ABSOLUTE_PATH>' -X utf8 -B '<RESTART_SCRIPT_READY_ABSOLUTE_PATH>' install --scheduled --require-existing-trust --wait-for-turn --message-file '<ABSOLUTE_PATH_TO_STARTUP_MESSAGE_JSON>'
```

Success with `TASK_NAME`/`SCHEDULED_WORKER_PID`/`RESULT_PATH` confirms scheduling; restart waits for this task to complete and no other active tasks.

### Finish and recovery

Once scheduled, report and end; no polling. Later verify restart, one complete message and loaded tools. Logs: macOS `~/.workbuddy/logs/wb-relaunch.log`, Windows `RESULT_PATH`. Never repeat restart or successful/unknown sending. Manual fallback: only confirmed unattempted sending.

Each Windows call cleans its temp scripts; workers clean requests and the Windows scheduled task. Report denied cleanup. Once the call ends, retry only allowed failed downloads/remaining checks. Never replay OAuth, completed setup/configuration or full preparation, change confirmed sources, or relax permissions.

## Troubleshooting

Missing tools: check enabled `openagent` in `~/.workbuddy/mcp.json`, Python/proxy/credential paths and `resume`. Verify result/recent-invocation tools and `openagent_run` boolean `async`; no test Agent runs.

## Report

Before scheduling, confirmed install/verification failure: `Installation failed: {reason}. {solution}` with an actionable fix. Sign-in timeout: step 3. Otherwise use only the matching two-line template. Configuration requires OAuth, MCP/trust checks and `PLUGIN_READY`; verify tools in the new task.

Configuration complete; restart scheduled:

```text
OpenAgent installation and configuration are complete.
WorkBuddy will restart after the current task completes and will send the startup message automatically.
```

End immediately; no claim of restart/delivery success. If cancelled, do not report or send again.

Configuration complete; automation unavailable; sending unattempted:

```text
OpenAgent installation and configuration are complete.
{brief reason automation was not run}; fully quit and restart WorkBuddy, create a new task, and send: {startup message}
```

With a request, append only `; also include your original business request` to line 2; send the request verbatim. If restarted, check the new task/input; if sending is unknown, check results above.

Incomplete, cancelled, denied or unknown:

```text
OpenAgent installation is not complete: {brief reason}.
Next step: {the currently actionable step}.
```
