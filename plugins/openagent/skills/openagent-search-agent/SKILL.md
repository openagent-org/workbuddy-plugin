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
4. On `selected`, complete Agent Selection's closing tool actions before entering `Result Validation and Delivery` for authorization validation and handoff to `openagent-run-agent`. Handle `timed_out` only after the same cleanup gate. On `cancelled` or a wait failure, go directly to `Failure Handling` without closing a tab. Keep this sequence in the same Turn.

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
3. Emit the Browser Handoff update. Use the [in-app browser procedure](#browser-display-boundary) to open the original `handoff_url` in a new tab. Bind the returned IDs to this `selection_id` for cleanup.
4. If Browser Use is unavailable or cannot confirm a unique, capable in-app browser before the first opening attempt, use WorkBuddy's built-in `present_files(files=[<original handoff_url>], cwd=<absolute working directory of the current WorkBuddy task>, explanation="Open the OpenAgent selection page")` once. Require a non-error result with `type=present_files_result` and a `previewed` count of 1. This route does not give ownership of a tab. If an opening attempt fails or its result is ambiguous, stop without waiting or opening a second page. Do not expose the handoff URL as a fallback link.
5. On `more_requested`, keep the same route and selection session. For Browser Use, navigate the owned tab with `mcp__browser__tab_goto({browser_id, tab_id, url: handoff_url})`; for the preview fallback, use the same `present_files` contract. Resume the wait only after confirmed success. Do not close or create a replacement tab on the native route.

**Output:** The original selection session and the confirmed opening route, with the owned tab IDs only on the native route; otherwise a handoff failure.

**Next:** After confirmed opening, immediately enter `Agent Selection` in the same Turn. Do not require a separate page-load check before listening for selection. Invalid or failed handoffs enter `Failure Handling` without calling the wait tool.

### Agent Selection

Input is an successfully opened Browser Handoff with a non-empty `selection_id` for the same session. Headless results and results without a selection handle must not enter this stage.

On `cancelled`, skip steps 4–5 and go directly to `Failure Handling`.

1. Browser Handoff has confirmed the discovery page opened. Regardless of whether the original request was to search, recommend, view, select, or find and run, emit the Agent Selection update and immediately use `selection_id` to call `openagent_wait_for_selection` through Wait and Close Orchestration in the same Turn. Do not deliver candidates first, end the Turn to await a new user message, or open the WorkBuddy Browser again.
2. Allow only one active wait call per `selection_id` at a time. The selection-wait update replaces the opening status; do not append another guidance message or repeat the update when resuming a pending orchestration call.
3. On `more_requested`, retain the same selection session and pass only the newly returned `handoff_url` to Browser Handoff. Do not search again or start a second simultaneous wait.
4. On `selected` or `timed_out`, retain the original wait result and follow [Close the Right-Side Built-In Browser](#close-the-right-side-built-in-browser) before any result update, execution handoff or final reply. The wait tool does not close the page.
5. Check the current task history for the close outcome or the specific reason the page could not be closed, including an opening through the preview fallback. Do not repeat a close attempt or retry the business request. Continue with the original wait result even if cleanup could not be confirmed.

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

- For `status=cancelled`, skip closing and do not check the browser again. Give only the localized reply "You have closed the OpenAgent discovery page." if existing trusted evidence confirms closure; otherwise give only "OpenAgent selection cancelled." Do not emit a stage update, reopen the page, or start execution.
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

Use the official WorkBuddy Browser Use tools in the current task. Call `mcp__browser__browsers_list` and select the unique `type="desktop"` entry named `WorkBuddy Browser`. Confirm multi-tab support with `mcp__browser__browser_info({browser_id})`. Read each non-error Browser Use reply as its JSON envelope; require `ok=true` and use `result`. If this browser or the required create, navigate, close and list tools are unavailable, use the caller's preview fallback before attempting to open anything.

Open the caller's original HTTPS URL once with `mcp__browser__tabs_new({browser_id, url})`. Require `result.claimed=true`, the same `browser_id`, and a new positive integer `tab_id`. Keep these IDs unchanged for this task and the specific discovery or result page that requested it. Never claim an existing tab. If an open was attempted but not confirmed, do not open a duplicate or switch to the fallback. A `present_files` receipt never provides tab ownership.

### Wait and Close Orchestration

1. After confirmed Browser Handoff, call `openagent_wait_for_selection` directly for the trusted `selection_id`; do not wrap it in a local JavaScript executor or implement MCP calls over HTTP. Keep only one active wait per session.
2. On `more_requested`, preserve the session, return the new URL to Browser Handoff, then resume waiting sequentially only after opening succeeds. Do not search again.
3. On `cancelled`, go directly to Failure Handling. On `selected` or `timed_out`, follow Agent Selection steps 4–5 before continuing.
4. Pass the original wait result unchanged to the next stage. Cleanup failure must not overwrite it or trigger another business request. Preserve authorization validation and the requirement to ask for task input when no business requirement exists.

## Close the Right-Side Built-In Browser

For an explicit close request, apply this procedure to the requested tab without starting a search or run. During selection, apply it only after `selected` or `timed_out`. Keep result pages open unless the user requests closure.

- Close only the tab created by this flow. Require its recorded `browser_id` and `tab_id` in the same WorkBuddy browser session, bound to the intended discovery or result page. Automatic selection cleanup may use only the current `selection_id` binding. If the target is ambiguous, was opened with `present_files`, or the session or IDs are missing or stale, leave it open. Never infer ownership from a URL, title, active tab or list position.
- Call `mcp__browser__tabs_close({browser_id, tab_id})` once with those exact IDs. Require `ok=true` and `result.applied=true` for the same two IDs. Then call `mcp__browser__tabs_list({browser_id})` once. Confirm closure only if its successful result array no longer contains that tab ID. A failed or uncertain call leaves closure unconfirmed; do not switch browsers, retry, or close another tab.
- This operation closes a page, not the right sidebar. Do not hide the panel, simulate a shortcut, or open a helper page. If an explicit close request cannot be fulfilled, tell the user briefly; during selection, preserve the original selection outcome.
