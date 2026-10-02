# IT-POL-EQ-001 — Company-issued equipment standard

| | |
|---|---|
| Owner | Internal IT |
| Applies to | Employees, managers, and directors |
| Catalog | Headphones, company phone, laptop |
| Effects | Approve, deny, or exception (`escalate`) |
| Combining algorithm | First applicable control. Stop at the match. |
| System of record | `evaluate_request` returns the effect and the control id |

This standard is the plain-language form of the procedure in [requirements.md](requirements.md). It does not add controls. Monitors, refresh cycles, replacement age, cost, and inventory are out of scope.

## 1. Purpose

Internal IT issues a small catalog of equipment under written controls. A request is approved only when a control says it is covered, refused only when a control says it is not, and sent to a person when the submission is incomplete or the standard marks it as an exception.

## 2. Scope

A request has four fields: the requester's name, the role, the asset, and the business reason. Role and asset are compared after trimming and lowercasing. No synonym is accepted. `headset`, `mobile`, `laptop computer`, `vp`, and `executive` are outside the catalog.

**Roles in this standard.** `employee`. `manager`. `director`, which means anyone above manager, and the field must already say `director`.

**Assets in the catalog.** `headphones`. `phone`. `laptop`.

The role on the request is the role that is evaluated. This standard does not look up the employee record, and it does not check equipment already on file.

## 3. Request types

The reason is classified, in lowercase, as the first type below that matches. That type is what the controls test. The words are signals, not a free-text judgment.

| Order | Type | When the reason has |
|---|---|---|
| 1 | `week_overlap` | All three: a keep-both phrase (`keep both` or `both laptops`), a duration (`week` or `7 days`), and `return`. This type wins over replacement language in the same sentence. |
| 2 | `unclear` | A count greater than one of headphones, phones, laptops, or pairs, such as `200 new headphones`. A span of days, such as `7 days`, is not an item count. |
| 3 | `unclear` | Both a second-asset signal and a first-asset signal. |
| 4 | `second` | Any of `second`, `spare`, `additional`, `another`, `extra`, `already have`. |
| 5 | `first` | Any of `first`, `do not have`, `don't have`, `not have one yet`. |
| 6 | `replacement` | Any of `replacement`, `replace`, `replacing`, `broken`, `broke`, `lost`, `stolen`, `worn out`, `stopped working`. |
| 7 | `unclear` | None of the above. |

## 4. Effects

| Effect | What it means | What happens next |
|---|---|---|
| `approve` | A control covers this request. | The asset is granted. The reply cites the control id. |
| `deny` | A control refuses this request. | The reply cites the control id and the statement. No one is asked to override it. |
| `escalate` | The submission is incomplete, outside the catalog, or named as an exception. | The request is queued for a person. The standard has neither approved nor refused it. |

## 5. Controls

Applied in this order. The first row that matches is the decision.

### 5.1 Intake

These three run before any entitlement. A request that fails intake never reaches the catalog.

| Control | Effect | Applies when |
|---|---|---|
| `blank_field` | Exception | The name, the role, the asset, or the reason is missing or only spaces. |
| `unknown_role` | Exception | The role is not employee, manager, or director. |
| `unknown_item` | Exception | The asset is not headphones, phone, or laptop. |

### 5.2 Laptops

Laptops are not issued under this standard. There is no approval control for them.

| Control | Effect | Applies when |
|---|---|---|
| `employee_laptop` | Deny | The role is employee and the asset is a laptop. The reason does not matter. |
| `laptop_week_overlap` | Exception | The role is manager or director, the asset is a laptop, and the type is `week_overlap`: hold both machines for a week, then return one to IT. |
| `laptop_not_covered` | Deny | Any other laptop request from a manager or director. |

### 5.3 Headsets

Every role in this standard may request headphones. The type decides the effect.

| Control | Effect | Applies when |
|---|---|---|
| `headphones_replacement` | Approve | The type is `replacement`. |
| `headphones_first` | Approve | The type is `first`. |
| `headphones_second` | Deny | The type is `second`. A spare while the current pair is kept is not issued. |

### 5.4 Company phones — employees

An employee phone entitlement is replacement only.

| Control | Effect | Applies when |
|---|---|---|
| `employee_phone_replacement` | Approve | The type is `replacement`. |
| `employee_phone_first` | Exception | The type is `first`. A first company phone is a person's decision. |
| `employee_phone_second` | Deny | The type is `second`. |

### 5.5 Company phones — managers and directors

A manager or director may hold one company phone.

| Control | Effect | Applies when |
|---|---|---|
| `manager_phone_replacement` | Approve | The type is `replacement`. |
| `manager_phone_first` | Approve | The type is `first`. |
| `manager_phone_second` | Deny | The type is `second`. |

### 5.6 Residual

| Control | Effect | Applies when |
|---|---|---|
| `unclear_reason` | Exception | The asset is headphones or a phone, and the type is `unclear` or `week_overlap`. |

There is no later control. Sections 5.1 through 5.6 cover every submission.

## 6. What is recorded

The decision record is only the effect and the control id:

```json
{"decision": "approve", "rule": "headphones_replacement"}
```

`rule` is the control id from the row that matched. The reply to the requester cites that id. An exception is queued with `flag_for_human_review` and is not treated as an approval.
