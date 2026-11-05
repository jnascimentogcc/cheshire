# Vision

## Problem

Someone has a requirement to implement ("notify customers by e-mail and SMS
when an order ships") but does not know which architectural capabilities it
needs, which approved solutions realise them, or what is easy to forget
(consent, retries, secrets, audit...). Architects know this, but mostly in
their heads, and they become a bottleneck answering the same kinds of
questions.

## Concepts

- **ABB (Architectural Building Block):** a technology-agnostic capability
  ("what"), e.g. *Channel: SMS*, *Consent management*.
- **SBB (Solution Building Block):** a concrete product, service or reusable
  component that realises an ABB ("how"), e.g. an SMS provider, an internal
  service.
- **Attribute:** a fact about a requirement from a closed vocabulary
  (personal data? volume? external boundary?). Rules read attributes.
- **Lens:** a cross-cutting concern (privacy, resilience, ...) used to
  interview architects and to discover attributes and implicit dependencies.
- **Rule:** an explicit, architect-owned statement that activates an ABB or
  makes an SBB eligible/ineligible under stated conditions.
- **Trace:** the machine record of which rules fired and why. The rationale is
  written from it.

## Users

| Profile | Uses the tool to |
|---|---|
| Architect | Maintain the catalog, start and close discussions, also consult |
| Functional team | Submit requirements, answer questions, read orientation |
| Technical team | Same, plus compare eligible SBBs and record the choice |
| Admin | Manage profiles and reassign discussions (can be the lead architect) |

## What it produces

For a requirement: the ABBs identified and implied (each with the text or rule
that justifies it), eligible / conditional / excluded SBBs per ABB with the
reason, explicit **gaps** (no coverage in the catalog), the **questions** still
needed to resolve uncertainty, and a rationale that cites the rules. The user
can record the SBB they chose and why (a decision record).

## Premise: no existing documentation

The tool must work for organisations whose architecture knowledge exists only
in architects' heads. So it also *captures* knowledge: starter pack, guided
interviews by lens, learning from corrections in real use, and discussions per
catalog item. Existing documentation, when present, only accelerates the start.

## v1 scope

In: catalog model and storage, deterministic engine, interpreter and writer
agents, consult UI, catalog maintenance UI, guided interview, per-item
discussions with a mediator, gap queue, YAML/JSON import/export.

Out: see "Out of v1" in `CLAUDE.md`.

## Principles

Simple over clever. Honest about what is not known. Rules over model opinion.
Useful with 10 catalog entries, better with 200. Evolvable by an open-source
community without rewriting the core.
