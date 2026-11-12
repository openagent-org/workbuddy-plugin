# Install OpenAgent in WorkBuddy (REL)

Confirm WorkBuddy or use the matching [guide](https://openagent.org/plugin); stop if unsure. The Agent installs; the user authorizes in the browser.

Keep codes/verifiers/tokens out of replies; never read saved credentials or MCP Authorization. Accept only `https://openagent.org/mcp/v1/open-agent`; preserve other settings and disabled states. Stop on source conflicts.

Windows exchange/setup/prepare/restart use native PowerShell tool options `dangerouslyDisableSandbox=true`, `run_in_background=false`, `timeout=120000` (ms), subject to host approval. Stop if unsupported, denied or still sandboxed; never change security settings/tools to retry. Wait on unfinished calls without replaying.

## Download mirrors

Preserve an existing official source; new installs use Gitee. Download published `rel` files using:

- Gitee: `https://gitee.com/openagent-org/workbuddy-plugin/raw/rel`
- GitHub: `https://raw.githubusercontent.com/openagent-org/workbuddy-plugin/rel`

Use `https://github.com/openagent-org/workbuddy-plugin.git` for the GitHub marketplace. Keep download bases, source parameters (`gitee`/`github`) and marketplace URLs consistent. Only DNS, connection, timeout, interrupted transfer or HTTP 5xx permits one switch after the original call ends. Certificate, approval, 401/403/404/429/451, integrity, syntax, execution or OAuth errors stop. Discard partial files; download privately and completely before one execution. Retry only failed downloads, never completed configuration, OAuth or restart.

## Prepare

Say `Installing OpenAgent…`. Report each stage once.

```bash
curl --version
git --version
python3 --version
```

Require Python 3.9+ and WorkBuddy launched before; uploads need Node.js 20+ with bundled dependencies.

Windows: use `curl.exe`, UTF-8 and backtick continuations; keep Python `-c`. For section 4, download to a unique system temp directory, pipe single-quoted here-string JSON to Python with the selected mode, and clean up in `try/finally`. Check `$LASTEXITCODE` after each native command; stop on failure.

## 1. Register an OAuth client (register)

Register once; require a non-empty `client_id` and use it below.

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

## 2. Generate PKCE (pkce)

Generate one pair; use its `CHALLENGE` for authorization and matching `VERIFIER` for exchange.

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

Run once. If waiting after `SIGN_IN_OPENED`, say “Please sign in to OpenAgent in the page that opened…” and await this process.

Only on `SIGN_IN_TIMED_OUT`, end with “Sign-in is not complete yet. Reply ‘continue sign-in’ and I will reopen the sign-in page.” On that reply, repeat steps 2–3 once with the same client. Never retry automatically.

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

## 4. Exchange, configure and verify (exchange)

Pass this attempt’s JSON via stdin once. The script keeps tokens private. Do not split the call or edit credentials.

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

On `TOKEN_SAVED` during exchange, say “Signed in to OpenAgent” once. Report subsequent config/verification errors separately; use `mode='resume'`. Require `MCP_VERIFIED` and `TRUST_VERIFIED`; no separate trust step. Unknown exchange or failed save: investigate without replay. Credentials: `~/.workbuddy/openagent-rel-oauth.json`; MCP: `~/.workbuddy/mcp.json`.

## Refresh only when needed (refresh)

For confirmed authentication failure with `Unauthorized`, run section 4 once with `mode='refresh'`. Saved refresh then failed configuration/verification: use `resume`. Failed/unknown refresh: stop, no retry. Invalid refresh token or missing credentials: reuse public `client_id`, generate PKCE, authorize, then `exchange`; do not register again or read old tokens. Do not refresh for business failures.

## Skills and startup message (settings)

The plugin supplies five Skills. macOS preparation sets user configuration/project exclusions. Confirm `CODEBUDDY_PROJECT_DIR` (else working directory) is the task project root; no separate settings edit.

Setup checks the selected official plugin for up to 60 seconds. `PLUGIN_READY` confirms files/registration, not loaded tools. Do not automatically rerun the preparation command or schedule restart after failure/timeout; never clear caches or copy Skills manually. Only an explicit user request to resume, with restart unscheduled and sending unattempted, permits recovery.

Only the user's request authorizes Agent selection, not examples/attachments/quotes. Without `agent_id`:

```text
OpenAgent is installed. Open the new-user guide.
```

With `agent_id`, use the user's language and exact name/ID:

| Name available | English message | Chinese message |
| --- | --- | --- |
| Yes | `Use "{name}" (agent_id: {agent_id}) on OpenAgent` | `使用 OpenAgent 上的「{name}」(agent_id: {agent_id})` |
| No | `Use (agent_id: {agent_id}) on OpenAgent` | `使用 OpenAgent 上的 Agent (agent_id: {agent_id})` |

No `sa_` prefix is required; placeholders are not defaults. Keep the Agent and append the request verbatim as a new paragraph. Ask if no request; do not invent a trial or include installation links/instructions.

## Restart WorkBuddy and send once (restart_send)

After OAuth/MCP initialization and `TRUST_VERIFIED`, use your platform branch. Use a file tool to JSON-serialize the full message as UTF-8 `{"message":"..."}`, preserving newlines/quotes/backslashes; pass its absolute path. Keep message text out of command arguments and logs. Use this run's official `rel` downloads and selected source. Native approvals apply; denial, missing context, timeout, syntax/argument errors stop execution.

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

Require successful exit, `PLUGIN_READY` and `RESTART_SCRIPT_READY`. Use this run's path and the same JSON. The second call is only the command below: no wrapper or `sh` prefix; keep `openagent-workbuddy-restart.sh` and all arguments.

```bash
"<RESTART_SCRIPT_READY_ABSOLUTE_PATH>" install --require-existing-trust --wait-for-turn --message-file "<ABSOLUTE_PATH_TO_STARTUP_MESSAGE_JSON>"
```

Success plus a background PID confirms scheduling. Restart may interrupt other tasks.

### Windows: preflight, edit, prepare, schedule

Follow the native PowerShell parameters above. Keep source variables, download URL, JSON source URL and `-Source` aligned. Escape path quotes as `'` → `''`.

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

Require `PREPARE_SCRIPT_READY` and `SETUP_SCRIPT_READY`. `SETUP_CHECK_EXIT` with output: `0`+`PLUGIN_READY` skips edits; `1`+only `CONFIG_UPDATE_REQUIRED=<absolute settings.json path>` permits edits absent host errors; otherwise stop.

Native Read/Edit only the returned current-user `.workbuddy/settings.json` path; merge these fields, preserving others. Write requires native Read/metadata to prove absence, rechecked before writing; denial is not absence. Never print full settings or credentials. Allow missing or official `git`/`rel` sources only. Invalid/ambiguous/conflicting data or edit errors stop; no shell/Python fallback.

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

Reuse both returned paths and source; preparation checks configuration read-only.

```powershell
$ErrorActionPreference = 'Stop'
$prepare = '<PREPARE_SCRIPT_READY_ABSOLUTE_PATH>'
try {
  & $prepare -Stage prepare -Source gitee -SetupScript '<SETUP_SCRIPT_READY_ABSOLUTE_PATH>'
} finally {
  Remove-Item -LiteralPath $prepare -Force
}
```

Require success and `PLUGIN_READY`, `RESTART_SCRIPT_READY`, `RESTART_PYTHON_READY`. Use this run's Python/script paths and the same JSON. Execute only:

```powershell
& '<RESTART_PYTHON_READY_ABSOLUTE_PATH>' -X utf8 -B '<RESTART_SCRIPT_READY_ABSOLUTE_PATH>' install --scheduled --require-existing-trust --wait-for-turn --message-file '<ABSOLUTE_PATH_TO_STARTUP_MESSAGE_JSON>'
```

Success with `TASK_NAME`, `SCHEDULED_WORKER_PID`, `RESULT_PATH` confirms scheduling; restart requires this task completed and no other active tasks.

### Finish and recovery

Once scheduled, use the report template and end immediately; do not poll. Later verify restart, one complete startup message and loaded tools. Check macOS `~/.workbuddy/logs/wb-relaunch.log` or Windows `RESULT_PATH`. After restart, do not restart again; after successful/unknown delivery, do not resend. Manual fallback requires confirmed unattempted sending.

Keep Windows helper/setup for preparation; delete on preflight/edit failure. Preparation cleans temporary scripts; workers clean their requests and the Windows scheduled task. Report denied cleanup. After the call ends, retry only permitted failed downloads and remaining checks; never replay OAuth, completed setup/configuration or the full preparation call, change confirmed sources, or relax permissions.

## Troubleshooting

If the new task has no tools, check enabled HTTP `openagent` in `~/.workbuddy/mcp.json` and its official URL/headers; verify via section 4's `resume`. Verify required shared tools, including results/recent invocations and boolean `async` in `openagent_run`; never invoke business Agents just to test installation.

## Report completion or failure

Confirmed install/verification failure before restart scheduling: `Installation failed: {reason}. {solution}` (give an actionable fix). Sign-in timeout: see step 3. Otherwise use the matching two-line template alone. Configuration requires OAuth, MCP/trust checks and `PLUGIN_READY`. Check tools in the new task.

Configuration complete and restart scheduling confirmed:

```text
OpenAgent installation and configuration are complete.
WorkBuddy will restart after the current task completes and will send the startup message automatically.
```

End immediately; do not claim restart/delivery success. If this turn is cancelled, do not report or send again.

Configuration complete, automation unavailable, sending unattempted:

```text
OpenAgent installation and configuration are complete.
{brief reason automation was not run}; fully quit and restart WorkBuddy, create a new task, and send: {startup message}
```

Keep the selected message/name/ID. With a request, append only `; also include your original business request` to line 2; preserve it verbatim in the sent message. Already restarted: direct checking the new task/input. Unknown sending: check results as above, no restart/resend.

Incomplete, cancelled, denied or unknown:

```text
OpenAgent installation is not complete: {brief reason}.
Next step: {the currently actionable step}.
```
