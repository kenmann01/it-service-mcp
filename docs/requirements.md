# Equipment request policy

This document is the only source of truth for an equipment request. Decide each request by the procedure below. Do not add rules about monitors, refresh cycles, years between replacements, cost, or inventory. The decisions are `approve`, `deny`, and `escalate`. `approve` when the policy clearly covers the request. `deny` when the policy clearly does not cover it. `escalate` when the request is ambiguous or missing information, so a human decides.

## Request

Every field is a string. A missing field, or a field that is empty or only spaces after trimming, is blank.

```json
{
  "employee": "name",
  "role": "role",
  "item_requested": "item",
  "reason": "the reason"
}
```

Before any rule, trim spaces and compare `role` and `item_requested` in lowercase.

Allowed roles:

- `employee`
- `manager`
- `director` (this value means anyone above manager; the field must already say `director`)

Allowed items:

- `headphones`
- `phone`
- `laptop`

Any other role string or item string is not allowed. Do not map synonyms. `headset`, `mobile`, `laptop computer`, `vp`, and `executive` do not match.

## Reason class

Classify `reason` in lowercase. Use the first class that matches.

1. `week_overlap` when the reason has all three of these:
   - `keep both` or `both laptops`
   - `week` or `7 days`
   - `return`
2. `unclear` when the reason states a count greater than one of headphones, phones, laptops, or pairs, such as `200 new headphones`. A span of days, such as `7 days`, is not an item count.
3. `unclear` when the reason has both a second-item signal and a first-item signal.
4. `second` when the reason has any second-item signal: `second`, `spare`, `additional`, `another`, `extra`, `already have`.
5. `first` when the reason has any first-item signal: `first`, `do not have`, `don't have`, `not have one yet`.
6. `replacement` when the reason has any replacement signal: `replacement`, `replace`, `replacing`, `broken`, `broke`, `lost`, `stolen`, `worn out`, `stopped working`.
7. `unclear` when none of the above match.

`week_overlap` wins over `replacement`. A reason that says both "replacing" and "keep both for a week before returning" is `week_overlap`.

## Decision procedure

Apply the first matching rule. Stop there.

1. Any required field is blank. Decision: `escalate`. Rule: `blank_field`.
2. Role is not `employee`, `manager`, or `director`. Decision: `escalate`. Rule: `unknown_role`.
3. Item is not `headphones`, `phone`, or `laptop`. Decision: `escalate`. Rule: `unknown_item`.
4. Item is `laptop` and role is `employee`. Decision: `deny`. Rule: `employee_laptop`. The policy does not cover employee laptops, whatever the reason says.
5. Item is `laptop`, role is `manager` or `director`, and the reason class is `week_overlap`. Decision: `escalate`. Rule: `laptop_week_overlap`. Keeping both laptops for a week and then returning the old one to IT is a human decision.
6. Item is `laptop` and role is `manager` or `director`, for every other reason class. Decision: `deny`. Rule: `laptop_not_covered`. No laptop request is approved.
7. Item is `headphones`, role is `employee`, `manager`, or `director`, and the reason class is `replacement`. Decision: `approve`. Rule: `headphones_replacement`.
8. Item is `headphones`, role is `employee`, `manager`, or `director`, and the reason class is `first`. Decision: `approve`. Rule: `headphones_first`.
9. Item is `headphones` and the reason class is `second`. Decision: `deny`. Rule: `headphones_second`. A spare pair while they keep the current ones is not approved.
10. Item is `phone`, role is `employee`, and the reason class is `replacement`. Decision: `approve`. Rule: `employee_phone_replacement`.
11. Item is `phone`, role is `employee`, and the reason class is `first`. Decision: `escalate`. Rule: `employee_phone_first`. An employee is approved only for a phone replacement; whether to grant a first company phone is a human decision.
12. Item is `phone`, role is `employee`, and the reason class is `second`. Decision: `deny`. Rule: `employee_phone_second`. An extra phone for an employee is not approved.
13. Item is `phone`, role is `manager` or `director`, and the reason class is `replacement`. Decision: `approve`. Rule: `manager_phone_replacement`.
14. Item is `phone`, role is `manager` or `director`, and the reason class is `first`. Decision: `approve`. Rule: `manager_phone_first`.
15. Item is `phone`, role is `manager` or `director`, and the reason class is `second`. Decision: `deny`. Rule: `manager_phone_second`. A second phone while they already have one is not approved.
16. Item is `headphones` or `phone` and the reason class is `unclear` or `week_overlap`. Decision: `escalate`. Rule: `unclear_reason`.

There is no later step. Steps 1 through 16 cover every request.

## Result

Return only this object:

```json
{
  "decision": "approve",
  "rule": "headphones_replacement"
}
```

`decision` is `approve`, `deny`, or `escalate`. `rule` is the rule id from the step that matched.
