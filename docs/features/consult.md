# Feature spec: Consult (draft)

Status: **agreed by the maintainer; open questions closed (section 9).** Global UI rules come from
`docs/ui-spec.md`; behaviour of the engine from `docs/rule-language.md`. All
profiles use this feature (login required, D26).

## 1. Purpose

Turn a requirement written in free text into: the ABBs it needs, the eligible
SBBs per ABB, the gaps, the questions still open, and a rationale grounded in
the rule trace, and let the user record which SBB they chose and why.

## 2. Model: one living page per session

A consultation is a **session** at `/consult/:id`. It is one page that updates
as the user answers, not a wizard. The engine is cheap and deterministic, so
every change recomputes the result immediately; the rationale (LLM) is
regenerated only on request.

Routes: `/consult` (list of sessions + new), `/consult/new`, `/consult/:id`.

Visibility in v1: a user sees their own sessions; architects see all.
(Sharing a session with a colleague is future work.)

## 3. Regions of the session page (in order)

1. **Requirement.** The text, read-only, with the spans the Interpreter used
   highlighted (highlight is never the only cue: each span has an index chip).
2. **What was understood.** Attribute table: attribute | value | source badge
   (`stated`, `inferred`, `answered`, `edited by you`, `unknown`) | span.
   Inferred values are editable; changing one marks it `edited by you`.
   Identified ABBs are listed with their span and can be removed or added from
   the catalog list (`identified by you`). ABBs activated by rules cannot be
   removed here (use feedback).
3. **Open questions.** Ordered as the engine orders them (by impact). Each
   shows the question, the options (the attribute's values plus "I don't know")
   and **what it affects** ("changes: Channel SMS, Consent"). Answering applies
   at once; the answered question moves to region 2.
4. **Result summary.** Counts: required, to consider, covered, conditional,
   blocked, gaps, potential. Also the validation status of what the result
   rests on ("2 of 11 rules are not yet validated").
5. **ABBs.** Grouped: *Required*, *To consider*, *Identified from your text*,
   *Potential (needs an answer)*. Each ABB card shows: name, plain description,
   activation and strength, validation badge, **Why?** (opens the trace:
   rule, reason, each test with value and source), coverage badge, then:
   - SBBs in alphabetical order with neutral state labels; each expands to
     *when to choose*, *limitations*, *characteristics*;
   - *Conditional* SBBs with the missing answer that would resolve them;
   - *Excluded* SBBs with the reason (prohibited, not applicable...);
   - for a **gap**: "No solution registered in the catalog for this building
     block. It was recorded for the architects."
6. **Comparison.** For each ABB with two or more eligible/conditional SBBs: a
   side-by-side table (columns alphabetical) of characteristics, when to choose
   and limitations. No sorting by quality, no "best" mark.
7. **Rationale.** Prose written from the trace. Each sentence carries reference
   chips that open the corresponding trace entry. A "Generate / Update
   explanation" button; when answers changed after it was written, a visible
   *outdated* notice. Checker warnings (unverified sentences) are shown, not
   hidden. Style follows the detail level (section 4).
8. **Record the choice.** Per ABB: select an SBB (eligible or conditional) or
   "decide later" or, for a gap, "will be handled outside the catalog", plus a
   reason (**required only** when the chosen SBB is conditional or deprecating;
   otherwise optional). Saved with author and time. A conditional choice shows a
   warning listing the unresolved questions.
9. **Feedback.** "Something is missing" / "Something is wrong" on a specific ABB
   or on the whole result, with free text. Creates a proposal in the
   architects' queue (later adopted as a discussion, D6/D7).
10. **Export.** Markdown and JSON of requirement, facts, result, rationale and
    choice records.

## 4. Detail level (progressive disclosure)

One toggle, **Summary / Detailed**, remembered per user. It changes how much is
expanded and the wording of the rationale (plain language vs technical). It
does not change permissions or the result.

## 5. Actions and flow

1. User writes the requirement and chooses *Analyze*.
2. Progress is shown by stage (interpreting, checking the catalog, evaluating
   rules) from the SSE stream; the result appears when the engine finishes.
   The rationale is then **generated automatically**, streaming into region 7
   without blocking the rest of the page. After that first generation it is
   regenerated only on request (the *outdated* notice tells the user when the
   answers have changed).
3. User answers questions / edits facts; the result updates.
4. User records choices, exports, or sends feedback.

Re-running with an edited requirement creates a **new revision** of the same
session; earlier revisions stay readable (answers and choices are kept with
timestamps and actors).

## 6. States (ui-spec section 7)

| Situation | Behaviour |
|---|---|
| Empty catalog | "The catalog has no building blocks yet." Architects get a link to the catalog; others are told to contact an architect |
| Interpreter finds no ABB | Explain, offer to rephrase, and record the text as an **unrecognised requirement** for architects |
| Interpreter output rejected by validation | One automatic retry; then a clear error, the text preserved, *Try again* |
| LLM provider unavailable | Error next to the affected region; edits to facts still work if an interpretation exists |
| Engine reports indeterminate | Never shown as an error: it is *conditional* / *potential* with its question |
| Rationale pending / failed | Loading and error live inside region 7 only |
| `proposed` (not yet validated) rules involved | Visible badge, never hidden |

## 7. Accessibility and content

- Recomputation announces a polite live-region summary ("3 questions left, 1
  gap") and does not move focus; after answering, focus stays on the next
  question.
- Badges always carry text. Coverage colours per `docs/tech-stack.md` section 6.
- The *Why?* trace is reachable by keyboard and available as plain text.
- All strings through Transloco; no fixed widths for labels.
- Rationale HTML/markdown is sanitised (ui-spec 12).

## 8. Data stored (see `docs/architecture.md`)

`Session` (requirement, revisions), interpreter output, answers and edits
(append-only, with actor and time), trace, result, rationale and model info,
`ChoiceRecord`, `GapEntry`, unrecognised-requirement entries, `Feedback`.

## 9. Decisions on the former open questions

1. The rationale is generated automatically on first load; later only on request.
2. A reason is required only when the chosen SBB is conditional or deprecating.
3. Visibility stays as is: owner + architects. Team sharing is future work.
4. Export is Markdown and JSON in v1. PDF, Word and ArchiMate come later
   (confirmed by the maintainer).
