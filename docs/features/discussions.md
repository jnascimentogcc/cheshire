# Feature spec: Discussions (draft)

Status: **agreed by the maintainer; open questions closed (section 12).** Global UI rules: `docs/ui-spec.md`.
Builds on D6 (per-item discussions with a mediator), D7 (whoever opens decides
and closes), D8 (no approval tiers; show the impact radius and notify all
architects) and D9 (the decision is a record). Related:
`docs/features/catalog-maintenance.md`.

## 1. Purpose

Give architects a light way to discuss a change to one catalog item, surface
disagreement and tacit knowledge, and leave a decision record that explains
*why* a rule or SBB is the way it is, so the rationale shown in consultations
can link back to it.

A discussion is **optional**: an architect may also validate directly (D28). Use
a discussion when input is wanted.

## 2. Roles and rules

| Who | Can |
|---|---|
| Opener (becomes the **decider**) | Edit the proposed change, ask the mediator, transfer the discussion, decide and close it |
| Other architects | Comment, state a position, ask the mediator |
| Admin | Comment, **reassign** the discussion (e.g. opener left or was deactivated) |
| User (non-architect) | Cannot take part and cannot read discussions; sees only the **decision summary** on the item; their input arrives as feedback from consultations |

- **One open discussion per item.** Opening a second one shows the existing one
  and offers to join it.
- **Transfer:** the opener hands the decider role to another architect; it takes
  effect immediately and is recorded (who, to whom, when). **Reassign:** same,
  by an admin; orphaned discussions (opener deactivated) appear in the admin's
  queue.
- No approval tiers, quorum or co-approvers in v1. The decision record has
  `decider` as a field so these can be added later (D9).
- A discussion is about **one primary item**; related items can be linked
  (read-only references).

## 3. Entry points and routes

Start from: the item page ("Start discussion"), a work-queue entry (claiming a
feedback or gap entry can open a discussion; the claimer becomes the opener),
or `/discussions/new`. A discussion can be about an **existing item** or about a
**new item that does not exist yet** (the proposal is the draft).

Routes: `/discussions` (inbox), `/discussions/new`, `/discussions/:id`.

**Inbox tabs:** *Needs my attention* (mentions, activity on discussions I
opened or joined), *Opened by me*, *All open*, *Closed*. Filters: item type,
domain, age, inactive for N days.

## 4. Discussion page (regions in order)

1. **Header:** item (link), status (`open` / `decided: accepted` / `decided:
   rejected` / `withdrawn`), opener-and-decider badge, participants, opened date.
2. **Proposal:** the pending change shown as a readable diff against the
   effective version (text, not colour only). Only the decider edits it; it is
   saved as a pending `ItemVersion` that does not affect consultations until
   validated (D28).
3. **Impact radius** (computed by code, never by the LLM): dependents (rules,
   SBBs), reference cases and recent consultations whose result would change,
   as in the catalog impact preview. A snapshot is stored when the discussion
   opens; a *Refresh* button recomputes and shows what changed since opening.
4. **Mediator brief** (pinned): summary of the item, its rules and usage
   (times used, times corrected), the impact radius in words, and open
   questions to the participants ("when would this not apply?").
5. **Thread:** chronological entries of four kinds, each visibly labelled by
   text (not icon alone): *comment*, *position*, *mediator*, *system* (opened,
   transferred, impact refreshed, proposal changed).
6. **Positions:** a table with one current position per participant:
   `support`, `support with conditions`, `oppose` or `abstain`, with a short
   reason. Updating a position keeps the history.
7. **Decide** (decider only; for others the panel is visible but disabled with
   an explanation of who decides).

## 5. Comments and positions

- Plain text with mentions of architects and links to catalog items. Comments
  can be edited (an "edited" marker and history are kept) and retracted (marked,
  not deleted).
- A **position** is a special comment: one live position per participant.
- New activity is announced politely to assistive technologies and never moves
  focus.

## 6. The mediator

An agent that facilitates; it **never decides** and never changes the item. Its
messages are labelled as AI-generated and cite what they rely on.

**When it speaks (v1):** it does *not* answer every comment, to avoid noise and
cost.
1. At opening: the brief (section 4.4).
2. On request: any architect can ask a question or press *Challenge this* (it
   argues the strongest counter-case and asks "when would this not apply?").
3. On *Prepare decision* (decider): a synthesis of the positions, the points of
   agreement and disagreement, the concrete change it suggests and a draft
   rationale. The decider can accept, edit or ignore it.
4. When code detects a problem: a rule that would introduce a dependency cycle,
   a duplicate, or a contradiction with another rule, found by the validator
   and the engine (facts), plus possible tensions the LLM suggests, labelled
   as suggestions.

**Guardrails:** neutral stance; must present counter-arguments and not simply
agree with the latest or most insistent participant; facts about the catalog
(counts, dependents, conflicts, usage) come from code and are passed to the
LLM, which phrases them; the same grounding checker used for rationales
rejects statements about the catalog that are not backed by those facts.

## 7. Deciding and closing

The decider chooses an outcome:
- **Accept as proposed**, **accept with modifications** (edit first), or
  **reject** (no change), or **withdraw** (opened by mistake).

On accept, the decider also chooses the resulting status of the new version:
`validated` (default) or `proposed`.

**Every `oppose` position must receive a response** from the decider: *accepted*
(and how it changed the proposal) or *not accepted* with the reason. The
decision cannot be saved without these responses. The synthesis from the
mediator can pre-fill them.

A confirmation dialog states the consequence (the discussion closes, the item
version changes). The **decision record** stores: decider, outcome, rationale,
the responses to opposing positions, the final impact (refreshed), the item
version produced, and the link to the full thread. It is shown on the item's
history and in the *Why?* trace of consultations that use the item.

A closed discussion cannot be reopened; a new discussion can reference it.

## 8. Notifications

Notifications are **in-application only** (no email in v1). All architects are notified when a discussion opens, with the impact radius
summary (D8); participants are notified of activity and mentions; the decider
is reminded when the discussion has been inactive for a configurable period
(default 7 days, `CHESHIRE_DISCUSSION_NUDGE_DAYS`; my default). Nothing closes
automatically.

## 9. States (ui-spec section 7)

| Situation | Behaviour |
|---|---|
| No discussions | Explain and link to "start from an item" |
| Item already has an open discussion | Show it, offer to join |
| Proposal conflicts with a newer item version | Show the newer version and a diff before continuing |
| Mediator unavailable (LLM error) | Error inside the mediator region only; thread, positions and decision still work |
| Mediator output fails grounding | Not posted; the failure is explained to the requester |
| Decider tries to save without responses to opposing positions | Inline error naming the missing positions |
| Decider deactivated | Appears in the admin's reassign queue |

## 10. Accessibility and content

Thread is a list with real headings; entry kinds are labelled in text; diffs and
impact are text; the decide dialog follows ui-spec 6.6; all strings through
Transloco; no fixed widths for labels.

## 11. Data stored (see `docs/architecture.md`)

`Discussion` (item ref, opener, decider, status, related items), `Comment`
(kind: comment | position | mediator | system, author, text, edits),
`Position` (participant, stance, reason, history), `ImpactSnapshot` (at open,
at decision), `Decision` (decider, outcome, rationale, responses to opposing
positions, produced item version), `Notification`.

## 12. Decisions on the former open questions

1. Notifications are in-application only in v1.
2. Closed discussions are never reopened; a new one can reference the old one.
3. The mediator speaks at opening, on request, on *Prepare decision* and when
   code detects a problem; it does not reply to every comment.
4. Stances stay `support`, `support with conditions`, `oppose`, `abstain`, and
   every `oppose` needs a response from the decider.
5. Non-architect users see only the decision summary on the item (decider,
   outcome, rationale, date), not the thread, positions or impact.
