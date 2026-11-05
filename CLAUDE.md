# CLAUDE.md

Project: **Cheshire**, after the Cheshire Cat from *Alice's Adventures in
Wonderland*. In the scene where Alice meets the Cat and asks which way to go,
the Cat guides her path depending on where she wants to get to. The project
does the same for a requirement: it orients the user towards the path (which
ABBs, which SBBs, and why), while the choice stays with the human. This is also
why the tool never ranks or decides for the user.

Open-source tool that helps architects capture and maintain a catalog of
Architectural Building Blocks (ABBs), Solution Building Blocks (SBBs) and the
rules that connect them, and helps everyone else (functional and technical
teams) turn a requirement into the ABBs it needs, the eligible SBBs, and a
decision rationale grounded in the catalog.

Read first: `docs/vision.md`, `docs/decisions.md`, `docs/rule-language.md`,
`docs/architecture.md`, `docs/tech-stack.md`, `docs/data-model.md`,
`docs/features/*.md` (consult, catalog maintenance, discussions), `docs/plan.md`.
UI standard: `docs/ui-spec.md`. The example catalog format is described in
`catalog/README.md`.

## Non-negotiable invariants

1. **The rule engine is deterministic and has no LLM dependency.** It lives in
   its own module. Dependency direction is agents -> engine, never the reverse.
2. **The tool never ranks or scores SBBs.** Results are listed in a stable,
   neutral order (alphabetical by id) with state labels. `prohibited` is an
   exclusion rule, not a ranking signal. Comparison is built from declared
   facts, not opinion.
3. **Unknown is a first-class value.** Conditions use three-valued logic
   (true / false / indeterminate). Never assume a missing answer; ask for it.
4. **The LLM translates, it does not decide.** It (a) maps free text to the
   catalog vocabulary and (b) writes prose from the engine trace. Nothing else.
5. **Everything an LLM returns is validated against the catalog** before use.
   Unknown ABB/attribute/value ids are rejected, never silently accepted.
6. **The rationale is grounded in the trace.** Every sentence cites trace
   entries; the writer may not mention an ABB or SBB that is not in the trace.
7. **Gaps are a first-class result** ("no coverage in the catalog"), shown with
   the same prominence as a recommendation, and recorded for catalog capture.
8. **Validation status is always visible** (`draft` / `proposed` / `validated`)
   on rules and entries, and surfaced in results. The engine only receives the
   **effective catalog**: latest `validated` version per item, else latest
   `proposed`; `draft` is excluded; a pending change never replaces a validated
   version (`docs/rule-language.md`, *Effective catalog*).
9. **v1 governance is one rule: whoever opens a discussion decides and closes
   it.** No approval tiers, quorum or configurable workflows in v1. Model the
   decision as a record (decider, outcome, rationale) so this can be extended.
10. **The product has its own UI and its own database.** No Git dependency in
    the product. Catalog import/export in open formats (YAML/JSON) is required.
11. **LLM providers sit behind an adapter interface.** Local models must be
    possible. No provider-specific logic outside the adapter.

## Out of v1 (do not build unless asked)

OR inside conditions, numeric comparisons, scores/weights, SBB-to-SBB rules,
numeric thresholds for volume/latency, approval tiers, configurable workflows,
post-project retrospectives, Git-based workflows, e-mail notifications,
PDF/Word/ArchiMate export, sharing consultations with colleagues, reopening
closed discussions, SSO/OIDC (design for it, do not build it).

## Working agreements

- All code, comments, docs and identifiers are in **English**. The chat with
  the maintainer is in Portuguese.
- Before changing an invariant or a recorded decision, read
  `docs/decisions.md` and ask the maintainer first.
- Engine work is test-first. `scenarios/*.yaml` are the acceptance contract:
  do not edit expected results to make tests pass without asking.
- Stack: `docs/tech-stack.md` is the Cheshire stack (derived from the
  sibling project STC's stack guide, no longer kept in this repo).
  `docs/ui-spec.md` is Cheshire's global UI standard. Open items in `docs/tech-stack.md` section 7 need the
  maintainer's answer before the work that depends on them.
- Work one milestone at a time, in the order of `docs/plan.md`.
- Keep the catalog file format (`catalog/`) stable and documented; it is the
  real public interface of the project.

## Repository layout

```
CLAUDE.md
README.md
docs/        vision, decisions, rule language, architecture, tech-stack, data-model, plan;
             ui-spec.md is the global UI standard
docs/features/ consult, catalog-maintenance, discussions (agreed feature specs)
catalog/     example catalog (fictional SBBs): attributes, lenses, ABBs, SBBs, rules
scenarios/   executable acceptance scenarios (interpreter output fixtures -> expected result)
```
