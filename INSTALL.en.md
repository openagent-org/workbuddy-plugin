# Install OpenAgent in WorkBuddy (REL)

Use this guide only in WorkBuddy. Confirm the actual client before proceeding. For other clients, skip these steps and use the matching guide from the [installation hub](https://openagent.org/plugin). If the client is unclear or no matching guide is available, stop and ask the user.

The WorkBuddy Agent performs the steps; the user personally completes browser authorization. Run steps in order and stop on failure. Do not expose an authorization code, PKCE verifier, access token, or refresh token.

On Windows, use WorkBuddy's native PowerShell tool. For every call that executes `openagent-workbuddy-exchange.py`, `openagent-workbuddy-prepare.ps1`, `openagent-workbuddy-setup.py`, or `openagent-workbuddy-restart.py`, set `dangerouslyDisableSandbox=true`, `run_in_background=false`, and `timeout=120000` (milliseconds) to request the native approval needed to write user installation settings or restart the app. These are tool arguments alongside `command`, not script arguments; do not use Codex's `sandbox_permissions`. This requests permission; the host determines approval and actual execution. Stop if the parameter is unavailable, approval is denied or times out, or the command remains blocked by the sandbox. Do not disable security settings or switch entry points to retry. Do not first run these scripts normally and then replay them. If the tool returns an unfinished task, wait on that same call. Skip macOS-only Bash steps and use the Windows PowerShell section below.

Windows uses the same official sources and download fallback rules as macOS: prefer Gitee, preserve an existing official source, and allow one switch to the other official source only for the download failures listed below. This guide depends on the new `scripts/openagent-workbuddy-prepare.sh` and `scripts/openagent-workbuddy-prepare.ps1`; publish them with their matching scripts to `rel` before publishing the website that references them.

Only accept configuration and credentials for `https://openagent.org/mcp/v1/open-agent`. Stop on other sources; do not relabel their `resource` or reuse their tokens. Preserve other MCP servers, custom fields, and disabled state when updating the current configuration. Recovery applies only after new credentials have been saved.

## Download mirrors

The installation Agent prefers `https://gitee.com/openagent-org/workbuddy-plugin.git`, with `https://github.com/openagent-org/workbuddy-plugin.git` as the fallback. Preserve an existing official source unless explicitly switching with `setup.py --source gitee|github`.

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

Python 3.9 or newer and a previously launched WorkBuddy installation are required. Attachment uploads require Node.js 20+. Upload dependencies are bundled with the plugin and need no separate installation. The final response must use exactly one of the two-line templates in section 8, with no heading, list, code fence, or extra explanation.

On Windows, use `curl.exe`, UTF-8 output, and backticks for curl continuation; keep Python `-c` blocks unchanged. For section 4, download the same `rel` script into a unique system temporary directory, pipe JSON from a single-quoted here-string into Python, and clean up with `try/finally`. Preserve the selected `exchange`, `resume`, or `refresh` mode. Check `$LASTEXITCODE` after each native command and stop on failure.

## 2. Register an OAuth client and generate PKCE

Register a public OAuth client:

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

`X-OASN-MCP-Legacy-SSE: enabled` permits WorkBuddy's legacy HTTP+SSE fallback while normal HTTP POST remains supported. It does not replace Bearer authentication. Trust is keyed by `SHA-256(URL.origin)::openagent` for the fixed origin `https://openagent.org`; it does not replace browser OAuth, host file approval, or connector enablement.

## 5. Refresh an expired Token

Only when OpenAgent is present and a request returns `Unauthorized` due to expired or failed authentication, change `mode='exchange'` in section 4 to `mode='refresh'` and run once. The program reads the private `client_id` and refresh token, saves the new credential, updates MCP configuration, verifies the connection, and rechecks trust without returning credential values.

If a refresh response was saved but later configuration or verification failed, use `resume`, not another refresh. If refresh fails or its result is unknown, stop. If the refresh token is no longer valid, reuse the existing public `client_id`, generate a new PKCE pair using only the PKCE command in section 2 without registering another client, authorize again in section 3, and perform one new exchange in section 4. Do not make the model read an old Token from MCP configuration.

## 6. Install Skills and prepare the startup message

The native plugin provides five Skills. Confirm Git first with `git --version`. On macOS, do not separately edit settings: section 7 first merges the `openagent-workbuddy` REL Marketplace and plugin enablement into `~/.workbuddy/settings.json`, and appends `openagent-workbuddy-restart.sh` to `sandbox.excludedCommands` in the current task project's `.codebuddy/settings.local.json`. It uses the absolute `CODEBUDDY_PROJECT_DIR` when supplied, otherwise the command's current directory; confirm this is the task project root. Each file is replaced atomically only when needed. Preserve other settings, existing exclusions, and file permissions; new files use mode `0600`. Reject source conflicts, invalid JSON or types, symlinks, and project settings write protection. A failure stops plugin verification and restart; the two files are not one transaction. Configuration alone does not prove the command was excluded or that restart succeeded.

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

Run only the branch for your platform, after OAuth, MCP merge and initialization, and `TRUST_VERIFIED` succeed. Use the file tool to create UTF-8 JSON `{"message":"the complete startup message"}`, preserving the selected message and business request, including newlines, quotes, and backslashes. Pass only its absolute path; keep message content out of command arguments and logs.

Follow "Download mirrors" and explicitly reuse the selected official source: preserve an existing official source; new installations default to Gitee. Use only scripts downloaded for this run from published `rel`, not workspace copies or historical files. Stop on denied approval, missing session context, unsupported arguments, timeout, or syntax failure.

### macOS: Prepare, then schedule restart

Use two separate Bash calls, each with `run_in_background=false` and `timeout=120000`. The first writes settings and the command exclusion, verifies the plugin, and prepares the restart script. The second lets the host evaluate the direct restart command under the updated exclusion. Do not combine calls, use host background mode, or set `dangerouslyDisableSandbox` to bypass approval.

Replace the message placeholder with the JSON's absolute path. Download the helper completely before execution; it sets the message file to `0600`, runs setup, and prepares the restart script. The call cleans up its temporary scripts.

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

Continue only after the call succeeds with `PLUGIN_READY` and `RESTART_SCRIPT_READY`. Plugin verification requires the selected official source, matching installed/cache versions of at least `0.2.84`, and the required files. A 60-second verification timeout is not grounds to clear caches, switch sources, or report completion.

Use this run's restart path and the same message JSON below. The second Bash call contains only this command: no `sh` prefix, wrapper, or extra checks; keep the filename `openagent-workbuddy-restart.sh`. Keep `--require-existing-trust`; an unsupported argument or host rejection stops the attempt.

```bash
"<RESTART_SCRIPT_READY_ABSOLUTE_PATH>" install --require-existing-trust --wait-for-turn --message-file "<ABSOLUTE_PATH_TO_STARTUP_MESSAGE_JSON>"
```

Once the command succeeds and reports the created background PID, immediately finish with section 8; do not poll. The worker waits for this task to complete before restarting and sending once. Restart forcibly exits WorkBuddy and may interrupt other tasks. The receipt confirms scheduling only.

### Windows: 1. Preflight and edit only when needed

Use the native PowerShell arguments and approval requirements at the start of this guide. For GitHub, change `$installSource` to `github` and `$installBase` to `https://raw.githubusercontent.com/openagent-org/workbuddy-plugin/rel` together; keep that source in step 2. Download the helper completely, then run read-only `preflight`.

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

Require this run's `PREPARE_SCRIPT_READY` and `SETUP_SCRIPT_READY`. Evaluate `SETUP_CHECK_EXIT` with the actual output, not the outer command's exit code:

| Preflight result | Next step |
| --- | --- |
| `0` and `PLUGIN_READY` | Skip editing; continue to step 2. |
| `1` with only `CONFIG_UPDATE_REQUIRED=<absolute path to the current user's .workbuddy/settings.json>` | Edit only if the host reports no denial, approval failure, or other exception. |
| Any other result | Stop; do not treat an ordinary failure as configuration required. |

Use native Read/Edit with normal approval, applying only the two fields below:

- Accept a missing marketplace or an official Gitee/GitHub git source with `ref=rel`. Stop on unknown sources, invalid structure, duplicate keys, or ambiguous edit targets.
- Use Edit for an existing file, preserving all other settings. Use Write only when native Read or metadata proves the file absent and it remains absent immediately before writing; unreadable does not mean absent. Stop if the file appears.
- Do not change MCP, trust, sandbox switches, or project settings, or expose full settings or credentials. Stop on edit, permission, or approval failure; do not fall back to shell/Python or repeat edits.

The example uses Gitee. For GitHub, set `source.url` to `https://github.com/openagent-org/workbuddy-plugin.git`, matching the selected source.

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

### Windows: 2. Verify the plugin and prepare the restart script

Reuse the helper and setup paths returned by step 1. Escape path single quotes as two single quotes (`'` → `''`). Keep the selected `-Source`; replace `gitee` with `github` below when applicable. This call verifies the edited configuration read-only and prepares the restart script; it does not schedule or perform restart.

```powershell
$ErrorActionPreference = 'Stop'
$prepare = '<PREPARE_SCRIPT_READY_ABSOLUTE_PATH>'
try {
  & $prepare -Stage prepare -Source gitee -SetupScript '<SETUP_SCRIPT_READY_ABSOLUTE_PATH>'
} finally {
  Remove-Item -LiteralPath $prepare -Force
}
```

### Windows: 3. Schedule restart

Proceed only after step 2 succeeds with `PLUGIN_READY`, `RESTART_SCRIPT_READY`, and `RESTART_PYTHON_READY`. Fill this run's Python and script paths and the same message JSON path, escaping single quotes as above. Run only this command:

```powershell
& '<RESTART_PYTHON_READY_ABSOLUTE_PATH>' -X utf8 -B '<RESTART_SCRIPT_READY_ABSOLUTE_PATH>' install --scheduled --require-existing-trust --wait-for-turn --message-file '<ABSOLUTE_PATH_TO_STARTUP_MESSAGE_JSON>'
```

Scheduling is confirmed only when the command succeeds and returns `TASK_NAME`, `SCHEDULED_WORKER_PID`, and `RESULT_PATH`. Immediately finish with section 8 without polling. Restart requires the current task to complete and no other tasks to be active. These results do not confirm restart, message delivery, or tool loading.

### Cleanup, failure handling, and acceptance

Successful or configuration-required Windows preflight retains the helper and setup for step 2. On preflight or editing failure, remove only this run's helper and setup. Step 2 removes the helper, setup, and temporary restart downloads. macOS removes its temporary scripts when preparation exits. Restart workers clean up their generated request files and the Windows scheduled task. If cleanup is denied, report the remaining paths and stop.

For an eligible download failure, wait for the original call to end and follow "Download mirrors": retry only the failed download and unexecuted checks, without changing the confirmed plugin source. Do not replay OAuth, completed configuration or setup, or the whole preparation command. Permission rejection never permits changing security settings, dropping required arguments, or switching execution routes.

The new task or later troubleshooting verifies old-process exit, new-instance launch, exactly one complete startup message, and required tools loaded; do not keep the installation task open for acceptance. Inspect `~/.workbuddy/logs/wb-relaunch.log` on macOS and this run's `RESULT_PATH` on Windows. If already restarted, inspect the new task without restarting again. If sending succeeded or is uncertain, inspect the result and task without resending. If automation is unavailable and sending is confirmed not attempted, use section 8's manual template and the same startup message; follow the actual restart state.

## 8. Report completion or failure

Choose a template for the actual state. Output only two plain-text lines, with no blank line or extra text. Fill placeholders without exposing sensitive values. Configuration is complete only after OAuth, MCP merge and initialization, trust readback, and `PLUGIN_READY` succeed; the new task verifies tool loading after restart.

When configuration is complete and section 7 confirms scheduling using the platform-specific results:

```text
OpenAgent installation and configuration are complete.
WorkBuddy will restart after the current task completes and will send the startup message automatically.
```

Report scheduling only, then immediately end the current task. Do not wait for or claim successful restart, sending, or tool loading; acceptance follows section 7. If restart cancels this turn, do not add a report or resend.

When configuration is complete, automation is unavailable, and sending is confirmed not attempted:

```text
OpenAgent installation and configuration are complete.
{brief reason automation was not run}; fully quit and restart WorkBuddy, create a new task, and send: {startup message}
```

Use the previously selected guide or Agent message for `{startup message}`, preserving the Agent name and ID supplied by the user. If a business request exists, append only `; also include your original business request` to the second line; preserve the full request in the message actually sent.

If restart already occurred, the second line should only direct the user to check the new task and input. If sending is uncertain, follow section 7 without restarting or resending.

For incomplete configuration, unknown status, failure, cancellation, authorization timeout, or another pending issue:

```text
OpenAgent installation is not complete: {brief reason}.
Next step: {the currently actionable step}.
```
