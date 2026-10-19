---
name: openagent-query-account
description: Use when the user asks for the currently signed-in user's OpenAgent balance, account information, Credits, or spending this month; not for top-ups, refunds, subscription changes, or accounts on other platforms.
---

# OpenAgent Account Query

## Purpose

Query and deliver the signed-in user's OpenAgent balance, usage this month, and account details link. Do not handle top-ups, refunds, subscription changes, or other platforms.

## Terminology

- **OpenAgent**: The platform and toolset used to discover, invoke, and manage Remote Agents.

## Language

Set `display_locale` to `zh-CN` or `en-US`: explicit user preference > trusted Host/caller locale > request/conversation language > `en-US`. Ignore code, quotes, Tool output, and fixed installation/selection prompts.

Use only the matching bilingual template; write free-form replies in `display_locale`. Keep stage names and English-only fixed copy in English; preserve Agent names, IDs, URLs, amounts, and files. `display_locale` is context, not a Tool argument.

## Status Update Format

On entering Account Query, send one standalone assistant commentary update before querying:

```text
OpenAgent: Account Query — <brief action phrase>
```

Keep the stage name in English and describe the current action in the user's language. Do not repeat the update or include results in it; deliver the account result or trusted failure explanation separately.

## Workflow

On an explicit OpenAgent authentication failure, follow [runtime sign-in](../openagent-login/runtime-sign-in.md) before other error, fallback, or completion rules. Otherwise keep this workflow unchanged. A user-requested retry of an unfinished sign-in goes there too.

Run `Account Query` once to query, validate, and deliver the result, then end.

## Workflow Stages

### Account Query

Input is the current user's OpenAgent account query request.

Before querying, check whether `openagent_account_credits` is exposed, with at most one Host lookup if needed. If it is missing, report that account queries are temporarily unavailable and stop. Do not fabricate account data or recurse from the guide's reward query into this Skill.

1. When the user asks for the balance, Credits, usage this month, or account details, call `openagent_account_credits` directly with no arguments.
2. If the exposed Tool is unavailable or fails for reasons other than authentication, report that account queries are temporarily unavailable and stop without automatically reinstalling or reauthorizing. Handle authentication errors through Runtime Sign-in. For an account that is not ready or downstream failures, report the trusted error or unavailability and stop. Do not switch to Agent execution, local scripts, or other tools to guess account data. Do not retry on your own, top up, or fabricate a balance.
3. Use only the Tool Result to report current Credits, Credits used this month, or unavailable status. Select the template matching `display_locale` below and replace the placeholders with trusted values. Display both the balance and usage this month with up to 4 decimal places. If a value has more than 4 decimal places, use decimal half-up rounding; then remove all trailing zeros from the fractional part and omit the decimal point when no fractional digits remain. For example, `0.0000` becomes `0`, `12.0000` becomes `12`, `12.3400` becomes `12.34`, and `1.23456` becomes `1.2346`. Preserve zeros inside the fractional part and at the end of integers; do not round up to an integer. For a missing balance or usage value, use “不可用” in `zh-CN` or “unavailable” in `en-US`, without inventing numbers or leaving placeholders. Do not display timestamps or append an “as of” date or time.
4. Render `details_url` unchanged as a Markdown link in the matching link placeholder when present; otherwise omit the entire details segment. Do not guess, compose, rewrite, or proactively open it.

| `display_locale` | Account message |
| --- | --- |
| `zh-CN` | 当前余额 {N} Credits，本月已消耗 {M} Credits，详情：{官网我的页面链接} |
| `en-US` | Balance: {N} credits · Used this month: {M} · Details: {account link} |

**Output:** Trusted balance, usage this month, and the available details link, or a public failure explanation.

**Next:** Deliver the result and end without automatic retries.

## Shared OpenAgent Rules

### Account Trust and Privacy

Account data comes only from the current dedicated account Tool Result. Do not output or infer payer, Owner, Pay account ID, OAuth Token, email address, or other internal account identifiers. Reward queries reuse these rules with their own required fields and output template.

## Close the Right-Side Built-In Browser

When the user requests closing the right-side built-in browser, first follow the [shared closing procedure](../openagent-search-agent/SKILL.md#close-the-right-side-built-in-browser) to write and open a temporary HTML file once through `present_files`, without starting Agent search, execution, installation, or account queries. Do not use `window.close()`. No page handle or additional close tool is required; do not claim closure without observing it. Do not repeat a closing attempt already made by the selection flow. Keep result pages open by default and close them only when the user explicitly requests it.
