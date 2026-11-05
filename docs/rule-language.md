# Rule language v1

Goal: the smallest language an architect can write in YAML without it turning
into programming. Three things are declared: **attributes**, **activation
rules** (condition -> ABB) and **SBB eligibility** conditions.

## 1. Values and `unknown`

Every attribute can take the value `unknown` (the default when not stated,
inferred or answered). `unknown` is never replaced by an assumption.

## 2. Conditions

A condition is a map of tests that must **all** hold (AND):

```yaml
when:
  personal_data: [personal, sensitive]   # attribute's value is one of these
  boundary: [external-partner]
  abb_present: [channel-sms, channel-email]   # at least one of these ABBs is confirmed
  except:                                  # nested condition, must evaluate to false
    interaction_mode: [interactive]
```

- Attribute test: true if the value is in the list; false if the value is known
  and not in the list; indeterminate if `unknown`.
- Multi-valued attributes (e.g. `regulation`): true if the intersection with the
  list is non-empty; false if known and the intersection is empty.
- `abb_present`: true if any listed ABB is currently *identified* (by the interpreter) or *confirmed* (by a rule); otherwise false.
- `except`: passes when its nested condition is false; fails when true;
  indeterminate stays indeterminate.
- An empty `when` is always true.

Evaluation is three-valued (Kleene AND): any false -> **false**; else any
indeterminate -> **indeterminate**; else **true**. OR is expressed with two
rules.

## 3. Attribute declaration

```yaml
- id: personal_data
  layer: core                 # core | extension
  values: [none, personal, sensitive]
  multi: false
  question: "Does this handle data about people? Is any of it sensitive?"
  ask_if: {}                  # optional condition; question asked only if not false
  applies_to_abbs: []         # extension only: asked when one of these ABBs is present
```

The attribute-to-lens link is declared once, on the **lens** (`feeds_attributes`).

Rules and SBB conditions may only use declared attributes and values
(validated).

## 4. Activation rule

```yaml
- id: R-001
  when: { ... }               # condition
  activates: consent-management
  strength: requires          # requires | considers
  reason: "Marketing messages to people need a legal basis and preferences."
  status: validated           # draft | proposed | validated
```

The engine applies rules repeatedly until nothing changes (fixed point). ABBs
only get added, so evaluation is monotonic. The catalog validator **rejects
dependency cycles** so that traces stay readable.

Per ABB, results are:

- **activation**: `identified` (from interpreter), `confirmed` (a rule
  evaluated true), or `potential` (a rule is indeterminate and none is true).
- **strength**: strongest among the rules that evaluated true (`requires` >
  `considers`); omitted when no rule activated the ABB. An `identified` ABB can
  also carry a strength if rules confirm it.
- **validation**: the weakest status among the rules that activated it.

Which catalog items take part is decided by the catalog layer, not the engine
(see section 10, *Effective catalog*).

v1 limitation: `abb_present` looks at identified/confirmed ABBs only. Rules downstream
of a `potential` ABB are not evaluated until it is confirmed.

## 5. SBB declaration and eligibility

```yaml
- id: sms-provider-a
  realises: channel-sms
  name: "SMS provider A"
  state: recommended          # recommended | accepted | deprecating | prohibited
  applies_when: { volume: [low, medium] }
  not_applies_when: { personal_data: [sensitive] }
  reason_not_applies: "Contract does not cover sensitive data."
  when_to_choose: "..."
  limitations: "..."
  owner: architect@example.org   # optional
  characteristics: { delivery_model: saas, data_residency: eu, cost_model: per-use }
  status: validated
```

Fixed decision order per SBB:

1. `state: prohibited` -> **excluded** (reason from `reason_prohibited`).
2. `not_applies_when`: true -> **excluded**; indeterminate -> mark conditional.
3. `applies_when`: false -> **excluded**; indeterminate -> mark conditional.
4. Otherwise **eligible** (an SBB with no conditions is always eligible),
   or **conditional** if step 2 or 3 was indeterminate. An absent
   `not_applies_when` never excludes.

There is **no ordering by quality**. SBBs are listed alphabetically by id; the
`state` is shown as a label. `characteristics` come from a small declared
vocabulary (`catalog/characteristics.yaml`) and feed the comparison.

## 6. Coverage per ABB

- **covered**: at least one eligible SBB.
- **conditional**: no eligible SBB, at least one conditional.
- **blocked**: SBBs exist, all excluded (each with its reason).
- **gap**: no SBB registered. Goes to the capture queue.

(Coverage is independent of activation: a `potential` ABB can be `conditional`
or `gap` too.)

## 7. Pending questions

For every `unknown` attribute that made a rule or an SBB condition
indeterminate, the engine proposes a question (if its `ask_if` is not false and,
for extension attributes, an `applies_to_abbs` ABB is present). Order:

1. impact = number of distinct ABBs having at least one indeterminate
   evaluation caused by that attribute (descending);
2. ties: attribute id (ascending), for determinism.

## 8. Trace

The trace is the source of truth for the rationale.

```yaml
- abb: consent-management
  activation: confirmed
  strength: considers
  validation: validated
  origin:
    - rule: R-002
      tests:
        - { test: "abb_present[channel-sms]", result: true }
        - { test: "personal_data in [personal, sensitive]", result: true, value: personal, source: inferred }
        - { test: "message_type in [transactional]", result: true, value: transactional, source: answered }
  coverage: covered
  sbbs:
    - { id: consent-platform, result: eligible, notes: [] }
```

## 9. Contract with the LLM

**Interpreter output** (validated; unknown ids are rejected and the interpreter
is re-prompted once, then the error is shown):

```yaml
abbs:
  - { id: channel-sms, span: "SMS" }
attributes:
  personal_data: { value: personal, source: inferred, span: "customer ... e-mail and SMS" }
  # source: stated | inferred | answered | edited (by the user)
```

**Writer input**: the trace plus catalog text of the referenced items.
**Writer output**: sentences each carrying `refs` to trace entries. A checker
rejects sentences with missing refs or with names absent from the trace.

## 10. Catalog validation (automatic)

- Attributes/values used in rules and SBBs exist.
- `realises` and `activates` point to existing ABBs.
- No dependency cycles among activation rules (an edge runs from each ABB in
  `abb_present` to the ABB the rule activates; a rule that activates an ABB it
  requires is a cycle).
- `except` holds a single level: `except` inside `except` is rejected.
- `abb_present` is not allowed inside `except` (it would make evaluation
  non-monotonic and the fixed point unstable).
- Attribute declarations: extension attributes need `applies_to_abbs`, core ones
  must not have it; `unknown` is implicit and never declared; ids `abb_present`
  and `except` are reserved.
- Every `status` is declared; `proposed` items are flagged in results.
- A prohibited SBB must state `reason_prohibited` (the database enforces it too).
- Warning: a cross-cutting ABB with fewer than two effective SBBs, or whose
  SBBs are all conditional.

### Effective catalog

The engine receives an **effective catalog**, assembled by the catalog layer
(the engine stays pure and unaware of versions):

- per item, the **effective version** is the latest `validated` version; if the
  item has none, its latest `proposed` version; `draft` versions are excluded
  (unless an architect asks for a test run that includes drafts);
- a newer, not-yet-validated version of an item that already has a validated
  one does **not** replace it;
- an item (rule, SBB) that references an excluded item (e.g. a rule that
  activates a `draft` ABB) is not effective either, and the validator reports
  the dangling reference;
- results carry the status of what they rest on (see *validation*).

## 11. Deferred (not v1)

OR in conditions, numeric comparison, weights/scores, SBB-to-SBB rules
(conflicts, prerequisites), numeric thresholds for volume/latency.
