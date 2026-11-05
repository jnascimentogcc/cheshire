# Decisions log

Short records of decisions taken during design. Reopen only deliberately.

| # | Decision | Why |
|---|---|---|
| D1 | Open source; simple scope; catalog + decision rationale are the core value | Genericity is the main weakness of LLM-only tools; the org's own catalog and an auditable rationale are the differentiators |
| D2 | Decisions are rule-based, clear rules; the engine is deterministic | Reliability, testability, true (not post-hoc) rationale, architects maintain rules not prompts |
| D3 | LLM only interprets requirements and writes the rationale from the trace | Keeps decisions consistent with the catalog; prevents invented or prohibited technologies |
| D4 | Assume no formal documentation exists; the tool must help capture knowledge | Open source: some orgs have everything documented, many have nothing |
| D5 | Capture via starter pack, lens-guided interview, correction in real cases, LLM-suggested drafts for architects to react to | Tacit knowledge surfaces in context; reacting is easier than writing |
| D6 | Per-item discussions between architects with a mediator agent | Surfaces disagreement, extracts tacit knowledge, leaves a decision history |
| D7 | Whoever opens a discussion approves and closes it | Clear ownership; avoids never-ending discussions |
| D8 | No approval tiers in v1, even though changes can affect several areas | Complexity; the project can evolve. Instead the mediator shows the impact radius and notifies all architects |
| D9 | Model the decision as a record (decider, outcome, rationale), permissions in a separate simple layer | Leaves the door open for co-approvers or other policies later |
| D10 | Own UI and own database; no Git in the product | Git is an extra layer; non-architect profiles should not need it. Open YAML/JSON import/export compensates |
| D11 | Version history per catalog item inside the product | Replaces what Git would have given: provenance and audit |
| D12 | Vague ranges (low/medium/high) for volume, criticality in v1 | Accept imprecision now; numeric thresholds are a future extension |
| D13 | The tool never ranks SBBs; it lists eligible ones with facts to compare | Removes the only subjective part of the engine; the choice belongs to humans |
| D14 | SBB state (recommended/accepted/deprecating) is a label; `prohibited` is an exclusion rule | Showing recommended first would be ranking by stealth |
| D15 | Security stays one lens (not split into identity vs data protection) | Privacy already covers part of data protection |
| D16 | 11 lenses (resilience and continuity merged) | Continuity lens was almost empty and overlapped with resilience |
| D17 | Two vocabulary layers: core attributes (all requirements) and extensions (tied to an ABB/domain, asked only when relevant) | Keeps the questionnaire small and the core stable |
| D18 | One kind of activation rule (condition -> ABB) covering both "ABB requires ABB" and "attribute triggers ABB"; two strengths: `requires` / `considers` | Fewer concepts; prevents flooding the result with minor ABBs |
| D19 | Conditions: all tests must hold (AND), `except` for negation; no OR in v1 (use two rules) | Simplicity; architects can write them in YAML |
| D20 | Cross-cutting ABBs (audit, secrets, monitoring, failure handling) are a marked category | They recur across requirements and repay curation most |
| D21 | Documentation and code in English; chat with maintainer in Portuguese | Open-source reach |
| D22 | The project is named **Cheshire**, after the Cheshire Cat in *Alice's Adventures in Wonderland*. In the scene where Alice meets the Cat, he orients her path depending on where she wants to get to; the project orients the user on the path of a requirement | The metaphor matches the design: it guides, it does not decide for the user (see D13) |
| D23 | Stack follows the sibling project's (STC) stack guide, now summarised in `docs/tech-stack.md`: Python/FastAPI/PostgreSQL 17, Angular/Tailwind/SpartanNG; Cheshire-specific differences are in `docs/tech-stack.md` | Reuse a proven stack; differences: DB is the source of truth, auth is required, no indexer or embeddings in v1 |
| D24 | `docs/ui-spec.md` is Cheshire's global UI standard | One normative source for design tokens, components, states and accessibility |
| D25 | LLM provider at launch is OpenAI behind the provider-neutral adapter | The maintainer already has the API key; adapter keeps Anthropic/local possible |
| D26 | Authentication: local accounts with cookie sessions, login required for all profiles (including consult-only), invite-only by an admin, internal installations behind a TLS proxy; OIDC later via a swappable module | Attribution is needed for decisions and sessions; internal use keeps v1 simple; domain stays independent of the auth method |
| D27 | Consult: one living page per session; the rationale is generated automatically on first load and later on request; a choice reason is required only for conditional or deprecating SBBs; sessions are visible to their owner and to architects; export is Markdown and JSON in v1 | See `docs/features/consult.md` |
| D28 | Catalog maintenance: `draft` items are excluded from normal consultations, `proposed`/`validated` are used and badged, a pending change to a validated item takes effect once validated; an architect may validate their own change (history shows who); reference cases and impact preview are in v1; imports land as `proposed`; work-queue claims expire | See `docs/features/catalog-maintenance.md` |
| D29 | Discussions: optional; opener is the decider (transfer by opener, reassign by admin); one open discussion per item; mediator speaks at opening, on request, on *Prepare decision* and on code-detected problems; stances support / support with conditions / oppose / abstain, and every oppose needs a response; in-app notifications only; closed discussions are never reopened; non-architects see only the decision summary | See `docs/features/discussions.md` |
| D30 | Data model: typed tables per catalog kind with composite foreign keys (kind enforced by the database), immutable versions, vocabulary values with immutable keys, effective-version and references views, full catalog snapshots; every evaluation stored; LLM runs kept by default; slugs immutable | See `docs/data-model.md` |

## Open questions

- Hosting and reverse proxy (internal installation; see `docs/tech-stack.md`).
- Which OpenAI models to use per agent role (configuration).
- Licence.
- Whether lenses 8, 10, 12 (observability, operations, evolution/cost) should
  feed attributes or stay as pure interview prompts (currently they feed none).
- Starter-pack governance (who curates, how communities contribute) and content.
- Prompts for the Interpreter, Writer, Interviewer and Mediator.
