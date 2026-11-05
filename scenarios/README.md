# Scenarios

Executable acceptance contract for the engine (milestone M1). Each file is a
fixture: what the **Interpreter** produced (so no LLM is involved), optional
user **answers**, and the **expected** engine result against `../catalog/`.

Fields in `expect.abbs.<id>`:

- `activation`: identified | confirmed | potential
- `strength`: requires | considers (omitted when no rule activated it)
- `validation`: weakest status among activating rules (asserted only when not `validated`)
- `coverage`: covered | conditional | blocked | gap
- `eligible`, `conditional`: SBB ids, alphabetical
- `excluded`: map of SBB id -> reason code (`prohibited`, `not_applies_when`, `applies_when_not_met`)

`expect.pending_questions` is ordered (see `docs/rule-language.md` section 7).
`expect.abbs` must list **all** ABBs in the result, and no others.

Do not edit expected results to make tests pass without asking the maintainer.
