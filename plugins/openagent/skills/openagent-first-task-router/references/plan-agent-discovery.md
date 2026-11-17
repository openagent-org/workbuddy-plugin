---
name: plan-agent-discovery
description: Convert requests to find Agents into oasn-search query plans while preserving tasks, hard constraints, and soft preferences. Called by the frontend or Host; does not execute searches or generate benchmark answers.
---

# Agent Query Planning

Input: the user's original request, explicit context, and any available trusted entity catalog.
Output: one JSON request containing query_plan, page, and size. Do not output explanations or ES DSL.
The caller distributes this Skill with its release. It requires no desktop documents; the search backend does not call a dialogue model.

## Extraction Rules

1. Preserve the original request in raw_query. Summarize the intended outcome in one sentence in goal; set query_language to the original language.
2. In intent_text, describe only the concrete task, objects, and deliverables. Remove filler such as "find me a tool" or "is there a tool."
3. Do not add an English translation, industry context, capability lists, or preferences that the user did not express.
4. "Restore the photo or remove its background; either is fine" describes alternatives: use a separate item for each. "Read, summarize, then send" requires multiple capabilities and must not become OR.
5. For discovery with explicit soft preferences, use agent-query-planner-v2. Items in required_capabilities are OR alternatives; each must independently describe its action, object, and deliverable.
6. With no preferences, a lookup by name, or a request to execute all steps, use agent-query-planner-v1 and omit discovery.
7. Each capability_name and capability_query_text describes only that alternative's own action and object. Do not copy the names of all alternatives into every item.
8. In capability_intent_query_text, explain why the user wants the task and what they want to obtain; do not copy a usage manual.
9. capability_id, canonical_action, and canonical_object are English snake_case request labels, not exact database IDs.
10. discovery.preference_text contains only explicitly preferred qualities, signaled by wording such as "preferably" or "prioritize." Do not turn them into mandatory conditions.
11. Extract 0-8 concrete short phrases for preference_keywords. Do not add Agent names, vague terms, or guessed synonyms.
12. Take entity_ids and capability_entity_ids only from a trusted catalog. Do not invent IDs when none are available.
13. Put explicit hard conditions for platform, permissions, deployment, language, or official status in filters. Do not infer a platform from the topic: "store analytics" does not imply Shopify.
14. Preserve unsupported hard constraints and explain them in planner_warnings. Clarify unknown entities first; never delete requirements to pass backend validation. The backend may return SEARCH_CONSTRAINT_UNSUPPORTED.
15. forbidden_effects contains only prohibited changes to external state: use message_send for "do not send messages/email," financial_transaction for "do not charge," and destructive for destructive actions such as deletion.
16. Use [] for arrays with no values and null for unconstrained official/publisher_verified. confidence indicates extraction confidence only.
17. Do not write scoring weights, ES parameters, expected result IDs, optimal candidates, or evaluation labels. Do not rewrite a plan based on search results.
18. Default to page=1 and size=100. For more results, reuse the same plan with the next page; do not introduce a separate pagination API.
19. size is the page size, not the number of relevant results. The current result window ends only when has_more=false.
20. "Do not retouch someone so much that they no longer look like themselves" is an outcome-quality requirement: put it in goal and that item's capability_query_text. Treat it as a preference only when explicitly qualified as preferred. It is not a forbidden_effects value, and retrieval cannot prove the actual effect has been verified.
21. "Do not update the calendar/board without confirmation" is still a conditional side-effect restriction. Preserve it verbatim in forbidden_effects and warn that it cannot yet be verified. Do not replace it with an unconditional write ban or remove it.
22. expected_output_types contains only explicitly mandatory file types: Word -> word, PPT -> powerpoint, Excel -> excel, PDF -> pdf, SVG -> svg, web page -> web_page. Use exact formats such as docx/pptx/xlsx when the user explicitly specifies the extension; otherwise use [] if no type is specified.
23. "Study schedule," "customer reply draft," and "shopping list" describe deliverable content: put them in capability_query_text and capability_intent_query_text, not the format array. Put "Java test source code" in task text; use java as a format only if .java is explicitly required.
24. Multiple expected_output_types in one item are all mandatory. For "Word, PPT, or PDF; any is fine," create three alternatives with word/powerpoint/pdf respectively, not one item containing all three. Do not add html to every alternative.

## Example

User: "I want to make old photos clearer, preferably keeping them natural without excessive skin smoothing."
This is discovery among similar tools, with an explicit preference for a natural appearance. Do not expand it into video, background removal, or layout tasks.

```json
{
  "query_plan": {
    "planner_version": "agent-query-planner-v2",
    "raw_query": "I want to make old photos clearer, preferably keeping them natural without excessive skin smoothing.",
    "query_language": "en-US",
    "goal": "Restore old photos while preserving a natural appearance",
    "intent_text": "Restore old photos, improve blur and image damage; prioritize a natural appearance.",
    "entity_ids": [],
    "required_capabilities": [{
      "capability_id": "restore_old_photo",
      "capability_name": "Old photo restoration",
      "canonical_action": "restore",
      "canonical_object": "old_photo",
      "capability_query_text": "Restore old photos, improving blur and image damage.",
      "capability_intent_query_text": "Make old photos clearer while preserving their original appearance.",
      "capability_entity_ids": [],
      "expected_output_types": [],
      "confidence": 0.95
    }],
    "forbidden_effects": [],
    "filters": {
      "platforms": [], "permission_classes": [], "deployment_modes": [],
      "languages": [], "lifecycle_status": [],
      "publisher_verified": null, "official": null
    },
    "planner_warnings": ["The user requests a natural appearance without excessive skin smoothing; retrieval relevance does not verify the actual effect."],
    "discovery": {
      "preference_text": "Preserve the original, natural appearance without excessive skin smoothing.",
      "preference_keywords": ["original appearance", "natural appearance"]
    }
  },
  "page": 1,
  "size": 100
}
```

Generate the plan once for the same request and context. Reuse it for pagination without repeatedly rewriting encoding text.
Evidence of a match in the current discovery mode does not establish user permission or successful execution of the complete task.
