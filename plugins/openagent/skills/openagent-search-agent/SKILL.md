---
name: openagent-search-agent
description: Use when the user asks to find, recommend, or select Agents with an explicit query, browse available Agents without a query, or an upstream business Skill requests headless capability discovery. Perform one discovery and selection protocol only; do not plan tasks, search again, or call execution tools.
---

# OpenAgent Agent Discovery

## Purpose

Complete a single OpenAgent discovery request. Direct user searches always open the WorkBuddy Browser and wait for a trusted user selection, with or without an explicit query. Background searches return complete candidates to the caller. This Skill does not plan business tasks, automatically search again, or call Agent execution tools.

## Terminology

- **OpenAgent**: The platform and tools for discovering, invoking, and managing Remote Agents.
- **Remote Agent**: A remote service callable through OpenAgent; it does not automatically inherit the Host conversation or local environment.

## Status Update Format

When entering a workflow stage, send a standalone assistant commentary update in this format:

```text
OpenAgent: <stage name> — <brief action phrase>
```

- Use the exact English workflow-stage heading for `<stage name>` and a short, verb-led action phrase in the user's language. Describe only the current action, without reasoning, results, next steps, candidate counts, internal identifiers, or handoff URLs; never claim success before authoritative confirmation.
- Emit one update on stage entry. Do not repeat it for tool polling, candidate-by-candidate checks, or resuming a pending call; re-entry may emit a new update.
- Deliver actual results separately. `Output` and `Next` describe internal data handoff and workflow transitions; do not display these labels to the user.
- For an upstream `presentation_mode=headless` request, suppress all user-facing stage updates, candidate-check notices, and UI; return data only to the caller, which owns progress reporting. On cancellation, go directly to Failure Handling and output only its fixed terminal reply, without another stage update.

## Workflow

On an explicit OpenAgent authentication failure, follow [runtime sign-in](../openagent-login/runtime-sign-in.md) before other error, fallback, or completion rules. Otherwise keep this workflow unchanged. A user-requested retry of an unfinished sign-in goes there too.

1. Run `Agent Search` once. Every direct user search uses browser presentation, with or without an explicit query; an upstream headless request uses headless presentation.
2. Pass a browser handoff result to `Browser Handoff` for validation and opening. Pass headless results to `Result Validation and Delivery`.
3. After `Browser Handoff` successfully opens the page, immediately enter `Agent Selection` in the same Turn. Use the shared Wait and Close Orchestration for every wait. On `more_requested`, return to `Browser Handoff` with the new URL, then resume selection on the same session.
4. On `selected`, complete Agent Selection's closing tool actions before entering `Result Validation and Delivery` for authorization validation and handoff to `openagent-run-agent`. Handle `timed_out` only after the same cleanup gate. On `cancelled`, stop any prewarmed close server without loading its page, then enter `Failure Handling`; other failures also enter `Failure Handling` directly. Keep this sequence in the same Turn.

### Loop Control

Call the search tool only once per discovery request. For `more_requested`, use only the new handoff URL returned by the wait result and continue waiting on the same selection session; do not start a new search. The caller decides whether to search again. Keep only one active wait per selection session at a time.

## Workflow Stages

Follow the orchestration in Workflow and transition only through each stage's `Next` contract.

### Agent Search

Input is an explicit query with constraints, a general browsing intent, or a headless request from an upstream business Skill. Emit the stage update before searching, except in headless mode.

Before searching, check that `openagent_search` and, for browser presentation, `openagent_wait_for_selection` are exposed, with at most one Host lookup if needed. If a required tool remains missing, report that search is unavailable and stop without searching, opening a selection page, or starting OAuth. Headless requests return the missing-tool result to the caller without UI or shell commands. A failed search with an exposed tool follows Failure Handling.

1. For every direct user search, with or without an explicit query, call `openagent_search(presentation_mode=browser)` once with `locale=zh-CN|en-US` matching the current user's language and a new stable `idempotency_key`. Pass explicit search terms as `q` (1–200 Unicode characters) to prefill and search the page, preserving names and constraints. Otherwise omit `q`; never invent terms. Do not pass other search filters. Retain the original request for post-selection handoff. Do not call `openagent_user_guide`.
2. For an upstream headless request, call `openagent_search` once with the supplied query, `presentation_mode=headless`, and the same locale rule; preserve the caller's query and constraints. In this mode, pass category, tags, sort, and pagination only when explicitly requested. Pass `category` only when the caller explicitly supplies a server-recognized category ID; never put natural-language search terms directly in that field.
3. Preserve the returned candidates and metadata without selecting, reordering, or inventing Agents. Do not open a browser or call `openagent_wait_for_selection` in this stage.

| Request source | `presentation_mode` | Result handling |
| --- | --- | --- |
| An upstream business Skill requests background capability discovery | `headless` | Do not display a Widget or the WorkBuddy Browser; return structured candidates only to the current caller |
| The user searches or browses available Agents, with or without an explicit query | `browser` | Do not show the Search Agents Widget; pass the returned handoff result to Browser Handoff, open the WorkBuddy Browser, and wait for selection |

“Find a PPT Agent”, “Find a stock analysis Agent”, “What is available in OpenAgent?”, and “Browse available Agents” all use `presentation_mode=browser` and open the WorkBuddy discovery page.

**Output:** One unchanged search Tool Result, including candidates and any presentation or selection metadata.

**Next:** Browser results enter `Browser Handoff`; headless results enter `Result Validation and Delivery`; errors or inconsistent presentation metadata enter `Failure Handling`.

### Browser Handoff

Input is the browser result from Agent Search or a trusted `more_requested` result from Agent Selection. This stage opens the page; it does not search or wait for selection.

1. For an initial browser result, require `presentation_mode=browser`, `browser_handoff=true`, `status=pending`, non-empty `selection_id` and `handoff_url`, and no Search Agents Widget binding. For `more_requested`, require the same trusted selection session and a new non-empty `handoff_url` from its wait result. Reject invalid handoffs before opening a page.
2. Use only the original absolute HTTPS `handoff_url` and `selection_id` from this result. Never construct, rewrite, or reuse a URL from another selection session. Use the complete URL only as the current browser-opening argument; do not expose short-lived tokens, bare URLs, or diagnostic logs.
3. For the initial browser result, resolve the packaged helper and close-page asset described below, then emit the Browser Handoff update and, in the same tool batch when the Host supports parallel calls, both invoke `python3 <absolute helper path> open` and call WorkBuddy's built-in `present_files` tool, not an MCP tool, once with `files=[<original handoff_url>]`, `cwd=<absolute working directory of the current WorkBuddy task>`, and `explanation="Open the OpenAgent selection page"`. The `cwd` argument is required. Prewarming is best-effort and must not delay or block the discovery-page opening when parallel calls are available.
4. Accept opening only when `present_files` returns a non-error result with `type=present_files_result` and `previewed` count equal to `1`. Independently validate a successful helper result using the closing-URL contract below and retain that internal URL only for this `selection_id`. If prewarming fails or its output is invalid, retain a prewarm failure marker and continue the successfully opened selection flow; do not retry yet. If page opening fails after prewarming succeeded, invoke `python3 <absolute helper path> stop --url <validated prewarmed URL>` once, then stop this selection flow and enter Failure Handling. Do not wait for selection or claim that the page opened. Do not expose the handoff URL as a fallback link, open an external browser, or use a shell command to open it.
5. For `more_requested`, open the newly returned URL with the same `present_files` contract and selection session. Keep the original valid prewarmed close URL and do not start another close server. Do not open the closing HTML at this point; close once through the shared procedure only after `selected` or `timed_out`.

**Output:** The same trusted selection session and a handoff page whose opening was confirmed by `present_files`, or a handoff failure.

**Next:** After confirmed opening, immediately enter `Agent Selection` in the same Turn. Do not require a separate page-load check before listening for selection. Invalid or failed handoffs enter `Failure Handling` without calling the wait tool.

### Agent Selection

Input is an successfully opened Browser Handoff with a non-empty `selection_id` for the same session. Headless results and results without a selection handle must not enter this stage.

On `cancelled`, skip steps 4–5 and go directly to `Failure Handling`. Do not load the closing page; only stop a valid prewarmed close server when one exists.

1. The discovery page opening has been confirmed by `present_files`. Regardless of whether the original request was to search, recommend, view, select, or find and run, emit the Agent Selection update and immediately use `selection_id` to call `openagent_wait_for_selection` through Wait and Close Orchestration in the same Turn. Do not deliver candidates first, end the Turn to await a new user message, or open the WorkBuddy Browser again.
2. Allow only one active wait call per `selection_id` at a time. The selection-wait update replaces the opening status; do not append another guidance message or repeat the update when resuming a pending orchestration call.
3. On `more_requested`, retain the same selection session and pass only the newly returned `handoff_url` to Browser Handoff. Do not search again or start a second simultaneous wait.
4. On `selected` or `timed_out`, retain the original wait result and perform the complete procedure in [Close the Right-Side Built-In Browser](#close-the-right-side-built-in-browser): reuse the validated prewarmed `/sandbox-preview/` URL for this selection session, or start the helper on demand only when prewarming failed, then pass the resulting URL to `present_files` once. Do this before reading or invoking `openagent-run-agent`, before emitting Result Validation and Delivery updates, and before any final reply, including the No Explicit Intent guidance. The wait tool returns selection data only and does not close the browser.
5. For `selected` or `timed_out`, skip these actions only when the current tool history records both a valid close URL for this selection session and a `present_files` attempt for that URL. The initial discovery-page opening, a terminal wait result, a plan to close, or this Skill's text is not cleanup evidence. If prewarming failed, one on-demand helper startup is required before declaring a concrete startup failure. If a missing packaged asset, helper startup, or unavailable Host tool prevents the attempt, retain that concrete failure in Host context and continue with the original selection result; do not pretend cleanup happened. An opening failure also preserves the selection result and must not trigger a business retry. Do not repeat an attempted close. This stage does not validate execution authorization or invoke an Agent.

**Output:** The unchanged trusted wait result from the same selection session. For `selected` or `timed_out`, retain the actual closing tool outcome or concrete inability to attempt it in Host context; `cancelled` requires no cleanup evidence. Do not add fields to the server result.

**Next:** `more_requested` returns to `Browser Handoff`. Only after steps 4–5 are handled may `selected` enter `Result Validation and Delivery`, or `timed_out` enter `Failure Handling`. `cancelled` and wait failures enter `Failure Handling` directly. Do not end the Turn between the successful wait, required closing actions, and authorization handoff.

### Result Validation and Delivery

Input is a complete headless search result or a trusted `selected` state. `cancelled` goes directly to `Failure Handling` without cleanup evidence checks. For browser results, pass the cleanup evidence gate below before emitting the Result Validation and Delivery update. Headless requests emit no update. Validate before delivering candidates or handing off authorization.

- For browser `selected` results, first verify the cleanup evidence required by Agent Selection step 5. If it is missing, return to Agent Selection step 4 before any update, handoff, or final reply. Headless results do not require browser cleanup.
- If `recommended_agent_id` is non-empty, `results` must contain exactly one matching candidate with a non-empty name. On mismatch, do not recommend or execute an Agent; enter Failure Handling. For headless requests, return the current query and trusted public error; for direct requests, explain that search results are temporarily unavailable and end.
- Determine whether candidates are empty only from `results` and trusted counts, not from a missing selection handle. Headless results may contain multiple candidates without a handle. Do not show an empty card or invent Agents.
- For a direct `search_only` request, complete the browser handoff and `openagent_wait_for_selection` in the same Turn first. After successful selection, enter the No Explicit Intent branch of `openagent-run-agent`; do not end the Turn early because the original request was only to search or select.
- `find_and_run` still returns only structured discovery results. The current caller decides whether to search again or execute. For direct user requests, hand off to `openagent-run-agent` only when an explicit executable prompt and trusted authorization already exist.
- Headless search returns complete model-readable candidates only. It creates no selection session, returns no Widget binding metadata, and does not enter the human-assisted discovery chain. The current caller selects a trusted Agent.
- Return headless search results completely unchanged to the current caller. Do not rewrite candidates, reorder results, or replace the upstream decision.
- For `status=selected`, pass the cleanup evidence gate above before continuing. Read only trusted `selected_agent`, `execution_authorization`, and `action`, preserving `selected_agent.name` and the Agent Card's `selected_agent.description`. A selection action provides server authorization only; it does not replace the user's business requirement. A general discovery request has no executable task. If the original request only searches, recommends, views, or selects an Agent, pass the trusted Agent to the No Explicit Intent branch of `openagent-run-agent` for its fixed two-line guidance. Do not use the selection action or an Agent default task to start a run; do not execute a default task.
- Normal public discovery returns `execution_authorization=null` and `action.type=none`. Validate the trusted `selected_agent` identity, then pass it with the user's original business requirement to `openagent-run-agent` using ordinary `agent_id` and `data`. If no business task was supplied, use its No Explicit Intent branch. A selected Agent is not authorization to invent a task.
- Only a legacy persisted trial selection may contain `execution_authorization.source=user_selection`, `immediate=true`, and `action.type=call_tool`. Validate its matching selection handle and bound idempotency key before handing it to the execution Skill; never reinterpret an invalid legacy authorization as an ordinary task. After validation, read the `openagent-run-agent` Skill if needed, or reuse it if already read in the current context. Immediately pass the selection result and authorization unchanged to `openagent-run-agent` in the same Turn. Do not end the Turn between `openagent_wait_for_selection` and `openagent-run-agent`.

**Output:** Complete candidate results, or validated and unchanged user selection authorization with the Selected Remote Agent.

**Next:** For headless requests, deliver results to the caller and end. With valid authorization, hand off to `openagent-run-agent` in the same Turn so it can determine whether an executable business requirement exists.

### Failure Handling

Input is a trusted failure result from search, selection waiting, handoff, or result validation. Emit the Failure Handling update except for headless requests and cancellation.

For cancellation replies, set `display_locale` to `zh-CN` or `en-US`: explicit user preference > trusted Host/caller locale > request/conversation language > `en-US`. Ignore code, quotes, Tool output, and fixed installation/selection prompts. Output only the matching single-language reply.

- For `status=cancelled`, skip browser closing and any new closing evidence checks: do not check, read, create, or open `close-tab.html`, and do not call `present_files`. If this selection session has a valid prewarmed URL, stop the prewarmed close server once with `python3 <absolute helper path> stop --url <validated prewarmed URL>`; this only releases the loopback listener and must not load the closing page. Ignore an already-stopped result. Do not emit a stage update. Use only existing trusted evidence of page closure; `status=cancelled` alone does not prove that the page is closed. If closure is confirmed, output only “你已关闭 OpenAgent 发现页。” for `zh-CN` or “You have closed the OpenAgent discovery page.” for `en-US`. Otherwise, output only “OpenAgent 选择已取消。” for `zh-CN` or "OpenAgent selection cancelled." for `en-US`. End selection; do not automatically reopen the page or continue Agent execution.
- For `status=timed_out`, verify Agent Selection step 5's cleanup evidence; if missing, return to step 4 before replying. Explain that selection timed out and end discovery. Do not automatically reopen the page.
- This Skill handles search, wait, and browser handoff failures locally; do not silently switch Agents. Use only trusted Tool Results, authoritative states, or stable public Host error codes. Without a stable public code, treat the error as unknown and do not retry automatically. Do not infer error category, authentication state, or retryability from message text.
- Headless failures must return the original search goal, constraints, trusted public reason, and all candidates already obtained to the current caller, without overwriting or fabricating results. For direct requests, show only a natural-language reason; hide raw results and internal fields.

**Output:** A caller-facing failure result preserving full context, or a trusted user-visible termination explanation.

**Next:** End the current discovery without silently searching again, reopening the page, or executing another Agent.

## Shared OpenAgent Rules

### Shared Protocol References

- Reuse [the shared rules of openagent-run-agent](../openagent-run-agent/SKILL.md#shared-openagent-rules) for post-selection execution authorization, Invocations, Sessions, attachments, and execution result delivery. Referencing a protocol does not authorize execution; hand off only after Result Validation and Delivery passes.
- This Skill owns search, candidate delivery, and UI Handoff. Callers must not independently rewrite the browser opening, waiting, or cleanup protocol.

### Result and User Boundaries

- Trust only candidates, metadata, and authorization returned by the search Tool. Return headless results completely to the current caller without fabrication, reordering, or rewriting.
- Raw Tool Results, selection handles, and Widget credentials are internal only. Use `handoff_url` only as the current Browser Handoff opening argument; do not output it as a link, expose bare URLs or parsed tokens, or log it.

### Browser Display Boundary

Open selection pages only through the built-in `present_files` contract in Browser Handoff. The original HTTPS handoff URL remains direct; the local server below is used only for the fixed closing page. Use only tools and schemas actually exposed by the current WorkBuddy Host; do not guess tool names, read another client's credentials, or use another client's browser runtime. If opening cannot be confirmed, stop and explain the failure without exposing the handoff URL as a fallback link, switching to an external browser, or installing extensions.

Send stage updates as standalone user-visible messages, not reasoning or tool logs. Keep only one active wait per selection session. Use the HTML closing procedure below; do not invent a page handle from `present_files`.

### Wait and Close Orchestration

1. After confirmed Browser Handoff, call `openagent_wait_for_selection` directly for the trusted `selection_id`; do not wrap it in a local JavaScript executor or implement MCP calls over HTTP. Keep only one active wait per session.
2. On `more_requested`, preserve the session, return the new URL to Browser Handoff, then resume waiting sequentially only after opening succeeds. Do not search again.
3. On `cancelled`, do not load the closing page; stop a valid prewarmed server as specified in Failure Handling and end. On `selected` or `timed_out`, execute Agent Selection steps 4–5. This orchestration is a Host procedure, not a tool that automatically closes the page. For these two statuses, the packaged asset, a valid prewarmed or on-demand close URL, and the closing `present_files` call must appear in the current tool history unless a concrete failure prevents them.
4. Pass the original wait result unchanged to the next stage. Cleanup failure must not overwrite it or trigger another business request. Preserve authorization validation and the requirement to ask for task input when no business requirement exists.

## Close the Right-Side Built-In Browser

When the user requests closing the right-side built-in browser, handle this section first without starting Agent search, execution, installation, or account queries. The selection flow also uses this section to close once after `selected` or `timed_out`. On `cancelled`, skip this section and end selection through `Failure Handling`. On `more_requested`, do not close, and continue the original selection session.

Use only the packaged asset `assets/close-tab.html`, resolved relative to this Skill. Do not create, copy, or overwrite a closing HTML file in `~/.workbuddy/browser-tools` or another runtime directory. Do not pass the asset path or a `/static-html/` URL directly to `present_files`: WorkBuddy 5.5.6 can suppress those local previews after a remote page is shown.

- Resolve `scripts/openagent-close-tab-server.py` relative to this Skill. The helper derives the exact sibling `assets/close-tab.html` path itself and rejects a missing file, symbolic link, or caller-selected target. For an initial selection Browser Handoff, prewarm it in parallel with the initial discovery-page opening by invoking `python3 <absolute helper path> open` once through the Host terminal. It binds only `127.0.0.1`, tries ports `19876` through `19885` in order, waits through the 1200-second selection window, and exits after the closing page is served or the safety timeout expires. A direct user close request starts it on demand instead.
- Require a successful helper exit and exactly one absolute URL with host `127.0.0.1`, an allowed decimal port from `19876` through `19885`, and path `/sandbox-preview/<non-empty random marker>/<absolute packaged assets/close-tab.html path>`. Reject any other output. This URL shape intentionally follows the WorkBuddy 5.5.6 preview-classification behavior; it is not a general sandbox mount or a public Host API.
- For `selected` or `timed_out`, use the valid prewarmed URL immediately. If no valid prewarmed URL exists, fall back to one on-demand startup and validate its URL with the same contract. Then call WorkBuddy's built-in `present_files(files=[<returned sandbox-preview URL>], cwd=<absolute current task directory>, explanation="关闭右侧内置浏览器")` once. The `cwd` argument is required. Treat the URL as internal and do not show it to the user.
- If the discovery page fails to open, selection is cancelled, waiting fails, or closing `present_files` fails before the page is requested, release a valid prewarmed server with `python3 <absolute helper path> stop --url <validated prewarmed URL>`. Never send an unvalidated URL to `stop`; stopping the service is not evidence that the browser closed.
- After opening, do not add this helper or asset to task artifacts, show or report them again, or mention them in visible reasoning, progress updates, or the final reply. The packaged page waits 300 milliseconds, clicks the matching visible close button, and otherwise removes its own iframe; it does not use `window.close()`. No page handle or additional Host close tool is required.

Execute the helper at most once during prewarming and at most once as the on-demand fallback; never start both after a valid prewarm. Call closing `present_files` only once. If the packaged asset is missing, both server startups fail, URL validation fails, or opening fails, preserve the original selection result and do not retry the business request. A successful `present_files` result confirms opening only; do not claim that the browser is closed without observing the closure. Keep result pages open by default and run this section for them only when the user explicitly requests closure. This compatibility path is specific to the verified WorkBuddy 5.5.6 classification behavior and must fail closed if a later Host version changes it.
