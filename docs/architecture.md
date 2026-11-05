# Architecture

Stack and package layout: `docs/tech-stack.md`. UI rules: `docs/ui-spec.md`.
Feature specs: `docs/features/` (consult, catalog maintenance, discussions).
Data model: `docs/data-model.md`.

## Blocks

1. **Rule engine** (independent library). Input: catalog + attribute values +
   interpreter ABBs. Output: results per ABB, pending questions, trace. No LLM,
   no I/O beyond what is passed in. 100% covered by scenario tests.
2. **Catalog and data** (single database). Entities below. YAML/JSON
   import/export.
3. **Agent layer**. Small roles:
   - *Interpreter*: requirement text -> ABBs and attribute values (with spans).
   - *Writer*: trace -> rationale and comparison, sentence-level refs.
   - *Interviewer*: lens-guided capture with architects; produces draft
     catalog entries to review.
   - *Mediator*: facilitates per-item discussions; never decides.
4. **LLM adapter**: one interface, structured outputs, swappable provider,
   local models possible.
5. **UI and API**: Consult (all profiles), Catalog maintenance (architects),
   Discussions (architects).

## Consult flow

requirement -> Interpreter -> validate against catalog -> Engine (effective
catalog) -> result shown (ABBs, SBBs per ABB, gaps, questions) -> user answers
or edits facts -> Engine again. After the first analysis the Writer generates
the rationale automatically (streamed, then checked); later only on request.
The user may record the chosen SBB and reason or flag "something is missing /
wrong" (D27).

Every session stores: requirement, interpreter outputs, answers, trace,
writer output, model/version used. Results are reproducible and debuggable.

## Capture flow

New or empty ABB -> Interviewer runs the lenses ("what does this need under
privacy?") and a pre-mortem ("what went wrong or was found late?") -> LLM
suggests candidate dependencies marked `draft` -> architect accepts / rejects /
"depends" -> entries become `proposed` -> an architect validates them
directly or, when input is wanted, through a discussion (D28, D29).
Also fed by: gap queue, "something is missing" feedback, starter pack.

## Discussion flow (per catalog item)

Opened by an architect (the opener becomes the decider). Mediator: summarises
the item and its rules, shows the **impact radius** (rules/SBBs depending on
it), notifies all architects, asks "when would this not apply?", flags
conflicts, brings usage evidence (times used, times corrected). Architects
comment asynchronously. Mediator proposes a concrete change and rationale;
the decider accepts or edits, and **records the opposing arguments and why they
were accepted or rejected**. One open discussion per item at a time. The opener
can transfer; an admin can reassign.

## Data model

The detailed model is in `docs/data-model.md`. The list below is the original
sketch, kept for orientation.

### Sketch

- `Attribute`, `Characteristic`, `Lens`
- `Abb` (cross_cutting flag, description, recognition hints, does-not-apply-when)
- `Sbb` (realises, state, conditions, when_to_choose, limitations, characteristics)
- `Rule` (activation)
- `ItemVersion` (item ref, version, content, status, author, timestamp, discussion ref)
- `Discussion` (item ref, initiator, status, participants, positions, proposed change, impact snapshot)
- `Decision` (discussion ref, decider, outcome, rationale, addressed opposing arguments)
- `Session` (requirement, interpreter outputs, answers, trace, result, rationale, model info)
- `ChoiceRecord` (session, abb, chosen sbb, reason)
- `GapEntry` (abb, sessions, count)
- `Feedback` (session, kind, text, converted-to-discussion)
- `User` (role: architect | user | admin); permissions in a separate layer

## Invariants for evolution

Decision stored as a record (not a boolean on the item); permissions
separate from domain logic; every result self-contained and reproducible;
catalog schema versioned.
