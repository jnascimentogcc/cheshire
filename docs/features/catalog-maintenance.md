# Feature spec: Catalog maintenance (draft)

Status: **agreed by the maintainer; open questions closed (section 14).** Global UI rules: `docs/ui-spec.md`.
Language and engine semantics: `docs/rule-language.md`. Decisions D6/D7 (per-item
discussions, opener decides) are implemented in a later milestone; this spec
must work without them and leave room for them.

## 1. Purpose

Let architects capture, correct and validate the catalog with as little friction
as possible, so it grows as a by-product of real use (gaps, corrections,
interviews) instead of as a documentation project. Everyone else can browse it
read-only, because the rationale of a consultation links into it.

## 2. Access

| Profile | Can |
|---|---|
| User | Browse the catalog read-only (items, rules, history, status) |
| Architect | Everything below |
| Admin | Same as architect, plus manage roles and reassign work |

Routes: `/catalog` (health + work queue), `/catalog/abbs`, `/catalog/sbbs`,
`/catalog/rules`, `/catalog/vocabulary` (attributes, characteristics, lenses),
`/catalog/reference-cases`, `/catalog/import-export`, and an item page per
entity (`/catalog/abbs/:id`, ...).

## 3. Catalog home: health and work queue

**Health strip** (counts, each a link to the filtered list): items by status
(`draft` / `proposed` / `validated`), ABBs without SBB (gaps), validator
errors and warnings, conflicts.

**Work queue** (the capture loop made visible). Each entry shows what, where it
came from and how often:
- **Gaps:** ABBs used in consultations with no SBB, with number of sessions.
- **Unrecognised requirements:** texts the Interpreter could not match to any ABB.
- **Feedback:** "something is missing / wrong" from consultations, with a link
  to the session and the affected ABB.
- **Drafts to review:** items produced by the Interviewer or imported.
- **Validation backlog:** `proposed` items waiting for validation.
- **Validator findings:** cycles, orphan ABBs, a cross-cutting ABB with fewer than two effective SBBs.

An architect can **claim** an entry ("I'll handle this"); it shows who claimed
it and prevents duplicate work. A claim **expires** after a configurable period
(default 7 days, `CHESHIRE_CLAIM_TTL_DAYS`) and the entry returns to the queue,
with a notice to the claimer shortly before; the claimer can renew it. Claiming a feedback or gap entry opens the
fitting editor pre-filled (new SBB for this ABB, rule linked to that session)
or, later, a discussion where the claimer is the decider (D7). Entries can be
dismissed with a reason.

## 4. Lists and item pages

**Lists** (ABBs, SBBs, rules): search, filters (domain, cross-cutting, status,
coverage, "used recently", "corrected often"), table per ui-spec 6.4. SBBs are
listed alphabetically; no quality sort.

**Item page**, same structure for every entity:
1. Header: name, id, status badge, current version, last change (who, when).
2. Content: structured fields (view mode).
3. **Connections:** for an ABB, the rules that activate it, the rules that use
   it in a condition and its SBBs; for an SBB, its ABB, conditions and
   characteristics; for a rule, the ABB it activates and everything its
   condition reads. Each is a link.
4. **Usage:** times used in consultations, times flagged or corrected, last
   used. This is the evidence for prioritising work.
5. **History:** every version with author, time, status and the change as a
   readable diff (text, not colour alone); restore creates a new version.
6. **Discussions:** placeholder region; becomes the per-item discussion list in
   M6 (opener decides and closes).

## 5. Editing

Structured forms, not raw YAML. A *YAML view* (read-only copy, optional edit)
is available for advanced users and matches the import/export schema.

- **ABB:** name, description, domain, cross-cutting flag, recognition hints,
  "does not apply when".
- **SBB:** name, the ABB it realises, state (label), conditions, reason fields,
  when to choose, limitations, characteristics (from the declared vocabulary),
  owner.
- **Rule:** the condition builder (section 6), the ABB it activates, strength,
  reason.
- **Save** creates a new `ItemVersion` with author and time. Optimistic
  locking: if someone saved meanwhile, show their version and a diff before
  letting the user merge.
- **Validator** runs on every edit. Structural errors (unknown id/value, cycle,
  dangling reference) block saving; warnings do not. Messages say what is wrong
  and how to fix it.
- **Archive instead of delete** for anything referenced or ever used; real
  delete only for unreferenced, never-used items.

## 6. Rule editor

Rows of tests, all of which must hold (AND), matching the language:
- *Attribute is one of* [values] (attribute picker restricted to declared
  attributes; values restricted to declared values).
- *ABB present: any of* [ABBs].
- *Except* group (nested test rows).
- An "also ask the user" hint is not needed: the question comes from the
  attribute declaration.

Beside the builder, a live **Try it** panel: set attribute values (including
`unknown`) and the present ABBs, and see the result of this rule
(true / false / indeterminate) with the same trace text users see. Nothing is
saved by trying.

## 7. Impact preview (before saving a change)

Because the engine is deterministic and cheap, every change shows what it
would do before it is saved:
1. **Dependents:** how many rules and SBBs reference the item.
2. **Reference cases:** each pinned reference case is re-evaluated with the
   change and the differences are listed (ABB added/removed, coverage changed,
   a question appears/disappears).
3. **Recent consultations** (last N, configurable): same comparison.
Differences are described in words with an icon and a label, never colour only.

**Reference cases** are consultations an architect pins ("this is how it
should behave"): the stored interpreter output and answers plus the expected
result, the product counterpart of `scenarios/`. They live at
`/catalog/reference-cases` and can be exported.

## 8. Status and versions

- `draft`: machine-suggested or incomplete. `proposed`: reviewed by a human
  once. `validated`: a named architect validated it.
- Interviewer/import output always starts as `draft`; **accepting** a suggestion
  makes it `proposed`; **Validate** is an explicit action that records the
  architect as decider.
- **Which version the engine uses:** `draft` items are not used in normal
  consultations (architects can include them in a test run); `proposed` and
  `validated` are used, badged; a pending change to a `validated` item does not
  affect consultations until it is validated (the previous validated version
  stays effective). See `docs/rule-language.md` section 10.
- Moving to `validated` can be done directly by an architect; a discussion
  (M6) is available when they want input, and then the opener decides.

## 9. Guided capture (Interviewer)

- **Start from an ABB or from scratch.** An assistant panel (streaming) walks
  the lenses (`catalog/lenses.yaml`): one question per lens, "not applicable"
  always available, plus a pre-mortem ("what went wrong or was found late?").
- Output is a **list of suggestions** (SBBs, rules, attribute values), never
  silent edits. Each suggestion shows its source in the conversation and
  offers *accept* / *reject* / *it depends* (the last asks one follow-up).
  Suggestions are marked `suggested by assistant` until a human accepts.
- The LLM may propose typical dependencies for an ABB for the architect to react
  to; they are `draft`.
- The conversation is stored with the resulting items as provenance.

## 10. Import and export

- **Export:** whole catalog or a selection, YAML or JSON, the same schema as
  `catalog/*.yaml`. Round-trip guaranteed.
- **Import (starter packs, other instances):** upload, validate, then a
  **dry-run diff** (added, changed, conflicting, invalid) before anything is
  written. Per-conflict choice: keep mine / take theirs. Imported items land as
  `proposed` (never silently `validated`).
- Import/export of reference cases uses the same mechanism.

## 11. Vocabulary management

Attributes, characteristics and lenses are edited like items, with extra care:
- Slugs and value keys are immutable; **names and value labels are editable**
  (a new attribute/characteristic version) and never cascade to rules or SBBs.
  To "rename" a key, create a new one and archive the old.
- A value or attribute in use cannot be archived; the screen lists every rule
  and SBB that uses it (from `item_refs_v`), and it can be archived once those
  have been changed.
- Starter-pack lenses can be marked "not used", never deleted.

## 12. States (ui-spec section 7)

| Situation | Behaviour |
|---|---|
| Empty catalog | Offer: import a starter pack, create the first ABB, or start the interview |
| Empty work queue | "Nothing waiting." with the last activity |
| Validator error | Inline, next to the field, and summarised at the top; save disabled with a reason |
| Concurrent edit | Show the newer version and a diff; nothing is lost |
| LLM unavailable | Only the Interviewer and suggestions are affected; manual editing works |
| Import with invalid items | List errors per item; the valid part can still be imported if the user chooses |

## 13. Accessibility and content

Condition builder fully keyboard operable with named controls; diffs and impact
messages are text; version history is a real table; Transloco for all strings;
no fixed widths on labels.

## 14. Decisions on the former open questions

1. Engine version: `draft` excluded from normal consultations; `proposed` and
   `validated` used and badged; a pending change to a validated item takes
   effect only once validated.
2. An architect can validate their own change directly; history shows who.
3. Reference cases and the impact preview are in v1.
4. Imports always land as `proposed`.
5. Work-queue claims expire (default 7 days, configurable; the period is my
   default, the maintainer only asked for expiry), renewable by the claimer.
