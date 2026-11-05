# Test script 3: discussions

Manual script for discussions (M6). Spec: `docs/features/discussions.md`. The rule being tested:
**whoever opens a discussion decides it and closes it.** Run it after script 1 (the catalog is
imported) on the same database.

## 0. Preparation

| | |
|---|---|
| App | `http://127.0.0.1:8090` |
| Accounts | Admin, Bea, Carl (architects) and Una (user), see `00-accounts.md`. One browser profile per person |
| Catalog | example catalog imported. `channel-sms` and `channel-email` validated (script 1, step 5), because a validated base shows the "stays in force" behaviour |
| LLM | `CHESHIRE_LLM_MEDIATOR_MODEL` set in `.env` (the Mediator is used from step 2) |

The Mediator is a language model: its wording changes between runs. Check what it **must** do
(cite facts, never decide, never rank), not the exact sentences. The impact numbers are computed
by the catalog and are exact.

Use the item `channel-sms` unless a step says otherwise. Its impact radius is 10 items: 7 rules and
3 solutions.

## 1. Where discussions live

1. As **Una** (plain user): there is no *Discussions* link in the header, and opening
   `/discussions` directly is refused or redirects. The notification bell is not shown either.
2. As **Admin**: the header shows *Discussions* and *Notifications*.
3. Open **Discussions**.
   **Expected:** tabs *Needs my attention*, *Opened by me*, *All open*, *Closed*, *Needs a new
   decider* (the last one only for admins); each empty tab has its own message. Filters: type,
   domain, "open for at least (days)", "quiet for at least (days)".

## 2. Open a discussion

1. As **Admin** open `channel-sms` and choose *Start a discussion*.
   **Expected:** the form asks for the item id (filled), an optional topic, an optional proposal
   (JSON) and says "Whoever opens a discussion decides it and closes it."
2. Topic: `Mention one-time codes`. Leave the proposal empty. Choose *Open the discussion*.
3. **Expected, the discussion page**, in this order:
   - header: "abb channel-sms", status "Open", "Opened by Admin on ...", "Decider: Admin";
   - proposal (no proposal saved yet) with *Edit the proposal*;
   - **Impact radius**: 10 items depend on it, 0 reference cases, 0 recent consultations, 0 new
     validator findings, and the list of dependents (R-001, R-002, R-003, R-004, R-006, R-007,
     R-009, `sms-provider-a`, `-b`, `-c`);
   - **Mediator**: an *AI-generated* opening brief, each sentence tagged (Fact, Question,
     Counter-argument ...) with "based on" references such as `usage` or `dependents`;
   - thread starting with "Admin opened the discussion and is its decider.";
   - positions, decision form, transfer form, history of positions.
4. **Expected, the brief:** it only states things the page shows (usage, dependents) and asks
   questions or raises counter-arguments. It does not say what to decide.
5. If the Mediator is unreachable, the discussion must still open with a clear message about the
   brief and a *Write the brief* button. (Optional: test with a wrong key, script 2 step 18.)

## 3. One open discussion per item

1. As **Bea** open `channel-sms`.
   **Expected:** the button reads *Join the open discussion*, not *Start a discussion*.
2. Open `/discussions/new` and try to start another one for `channel-sms`.
   **Expected:** "This item already has an open discussion. Join it instead." with a *Join the
   discussion* link.
3. Join. **Expected:** Bea appears under "Taking part".

## 4. Comments, mentions, links

1. As **Bea** write `I worry about OTP flows, see sbb:sms-provider-a.` and post.
   **Expected:** `sbb:sms-provider-a` is a link to that solution.
2. Mention Carl with the *Mention* list and post another comment.
   **Expected:** Carl gets a notification (step 11).
3. Edit Bea's second comment (*Edit*, change a word, save).
   **Expected:** it shows "edited"; the earlier text is kept in the record.
4. Retract the second comment.
   **Expected:** it shows "retracted" and is not deleted from the thread.
5. As **Admin** try to edit Bea's comment. **Expected:** not offered.

## 5. Positions

1. As **Bea** choose *Oppose* and leave the reason empty, *Save my position*.
   **Expected:** refused: a reason is required for oppose.
2. Reason `Breaks OTP wording`, save. **Expected:** listed in *Positions* as Bea, Oppose, with
   the reason. A line also appears in the thread.
3. Change Bea's position to *Support with conditions* with a reason, then back to *Oppose*.
   **Expected:** only the latest is live; *History of positions* lists the earlier ones as
   "replaced" and "(changed N times)" shows in the table.
4. As **Carl** choose *Support* without a reason. **Expected:** accepted (no reason needed for
   support or abstain).

## 6. The proposal

1. As **Bea** (not the decider) open the proposal area.
   **Expected:** she cannot edit it; the editor is for the decider only.
2. As **Admin** open *Edit the proposal*.
   **Expected:** a JSON editor already holding the current item (so you only change what you
   want).
3. Change `description` to `Sending text messages to mobile numbers, including one-time codes.`
   and choose *Save the proposal*.
   **Expected:** "Proposal saved as draft version 2. It does not affect consultations until it is
   accepted." and a readable change: description changed from the old text to the new one. The
   thread says "Admin changed the proposal."
4. As **Una** or in another window, run a consultation mentioning SMS, or open `channel-sms`:
   **Expected:** the item still shows the **old** description and no pending notice for a plain
   user. The draft is invisible to consultations.
5. As **Admin** break the JSON (remove a closing brace) and save.
   **Expected:** "That is not valid JSON." and nothing is saved.
6. Validator problems (use a discussion on a solution, for example start one on
   `sms-provider-c` and open its proposal): set `realises` to `no-such-abb` and save.
   **Expected:** the validator problems are posted in the thread as a mediator message marked
   "Found by the validator, not by the language model." and the proposal is not accepted as
   valid. Restore `realises` and close that discussion as *Withdrawn* when done.
7. Back in the `channel-sms` discussion: **Expected, impact:** the *Impact radius* still shows the dependents; choose *Refresh*.
   *Changed since the discussion opened* says "Nothing changed since the discussion opened." (the
   description change does not alter any result).

## 7. Talking to the Mediator

1. *Ask the mediator*: `What would break for sms-provider-b?` and choose *Ask*.
   **Expected:** while it works, "The mediator is working..." appears and the rest of the page
   stays usable (you can still comment). The reply cites facts and does not decide.
2. Choose *Challenge this*. **Expected:** counter-arguments and questions, again tied to facts.
3. **Expected, always:** no message says one option is best, recommended over another, or
   better. If you see ranking words or an ABB or solution that is not in the facts or impact,
   report it.
4. **Expected, failure of grounding:** if a reply fails the checker twice, nothing is posted and
   a message says the output was rejected; this is rare and counts as a pass.

## 8. Deciding: the checks

1. As **Bea** (not the decider) look at *Decision*.
   **Expected:** "Only Admin decides this discussion." No decide controls.
2. As **Admin** choose *Prepare the decision*.
   **Expected:** the Mediator posts a synthesis: sentences with references such as
   `position:1`, a *Suggested change* and a *Draft rationale*. The decision form shows "The
   mediator prepared a synthesis. You can use it, edit it or ignore it." with *Use the draft
   rationale*. It also prefills a response for Bea's objection.
3. Clear the rationale and choose *Decide...*.
   **Expected:** "Write the rationale of the decision." Nothing is sent.
4. Write a rationale, clear the response to Bea's objection and choose *Decide...*.
   **Expected:** "Answer every opposing position before deciding: Bea." No dialog.
5. Fill the response (choose *Objection accepted* or *not accepted*, write how you answer it).

## 9. Deciding: stale proposal

1. Open `channel-sms` in another window as **Bea** and save a change to *Limitations* as
   *proposed*. (This is a newer version than the one the discussion started from.)
2. As **Admin** reload the discussion.
   **Expected:** a notice: "The item was changed by someone else after this discussion opened
   (version 1 to 3). Differences:" with the differences, and the decision form asks you to tick
   "I have read the newer version and still want to decide."
3. Try *Decide...* without ticking. **Expected:** refused. Tick it.

## 10. Deciding and closing

1. Outcome *Accepted with modifications* or *Accepted as proposed*; result status *Proposed*.
   Choose *Decide...*.
2. **Expected, the confirmation dialog:** "Confirm the decision" with the consequence in words:
   "The discussion closes and the proposal for abb:channel-sms becomes a version with status
   Proposed." *Cancel* closes it and nothing changes. The dialog is centred and keyboard
   operable (Escape closes it).
3. Choose *Confirm and close*.
   **Expected:**
   - status "Decided: accepted"; a **Decision record** with outcome, "Decided by Admin", the
     time and "produced version N (Proposed)", the rationale, and "Responses to opposing
     positions" with Bea's objection and your answer;
   - the proposal and the impact radius stay visible, with the numbers as at the decision;
   - no more comment, position or decide controls; "This discussion is closed. A closed
     discussion is never reopened; a new one can refer to it."
4. Open `channel-sms`. **Expected:** the **validated** version is still the one in force (the
   new one is only proposed); the history shows the new version with origin "From a
   discussion". Validate it, then the content changes.
5. As **Una** (plain user) open `channel-sms`.
   **Expected:** a decision summary (outcome, decider, rationale, date) but no link to the
   discussion thread and no "Start a discussion" button.

## 11. Rejection, withdrawal and a new item

1. As **Carl** start a discussion on `channel-email`, save a proposal with a changed
   `description`, then decide **Rejected** with a rationale.
   **Expected:** closed, "Decided: rejected"; the item stays as it was; the proposal remains in
   the history as a draft.
2. As **Carl** start a discussion for a **new** item: id `consent-lite`, type ABB (use the
   `/discussions/new` form), with a proposal JSON for a new building block. Then **Withdrawn**.
   **Expected:** the discussion closes with "Withdrawn"; the new item ends up archived and does
   not appear in the default catalog list.
3. Start another new-item discussion (`consent-lite2`) and decide **Accepted as proposed** with
   status *Validated*. **Expected:** the item exists, validated, with origin "From a discussion".

## 12. Transfer and reassign

1. As **Admin** start a discussion on `audit-log` (topic `Rename audit log`).
2. In *Transfer the discussion* choose Bea and give a reason, *Transfer*.
   **Expected:** Bea is now the decider at once; the thread and the page record "from Admin to
   Bea" with the reason. Admin can no longer decide it (unless reassigned).
3. Deactivate **Bea** (`00-accounts.md`, section 3). As **Admin** open the discussion list.
   **Expected:** the discussion shows a "decider left" badge; the tab *Needs a new decider* lists
   it (admin only).
4. In *Reassign the discussion* choose Carl, *Reassign*.
   **Expected:** Carl is the decider; the record shows the reassignment as such. Reactivate
   Bea afterwards.

## 13. Inbox tabs and filters

1. As **Admin**: *Needs my attention* lists discussions where you decide and have something new,
   or where you are named; *Opened by me* lists your own; *All open* lists every open one;
   *Closed* the decided ones.
2. Filter by type `abb` and then by an item that has none. **Expected:** the table updates and
   shows "Nothing matches" style empty text.
3. Open a discussion that has new activity from someone else, then go back.
   **Expected:** it is no longer in *Needs my attention* (marked as seen).

## 14. Notifications

1. As **Carl** open **Notifications** (or use the bell with its unread count).
   **Expected:** entries for "A discussion was opened", "Activity in a discussion" and "You were
   mentioned" (step 4.2). *Open* goes to the discussion; *Mark as read* lowers the count;
   *Mark all as read* clears it.
2. Notifications exist only in the app (no e-mail).
3. Leave a discussion with Admin as decider untouched for the nudge period. To test without
   waiting 7 days, set `CHESHIRE_DISCUSSION_NUDGE_DAYS=0`, restart the API and refresh the page.
   **Expected:** a "A discussion you decide has gone quiet" notification, created once.
   Put the value back.

## 15. Live updates

1. Open the same discussion as **Admin** and **Carl** in two windows.
2. Carl posts a comment.
   **Expected:** within about 20 seconds Admin's page shows it without a reload, and a polite
   status line announces it. Anything Admin was typing is not lost.

## 16. Work queue link

1. As an architect, with a consultation that left a gap or feedback (script 2, step 11), claim
   the entry in the work queue (*I'll handle this*).
2. **Expected:** the entry now offers *Start a discussion*. It opens the new-discussion form for
   the right item with a note that it comes from work-queue entry N. You become the decider.

## Result sheet

| Step | Pass | Notes |
|---|---|---|
| 1 Where discussions live | | |
| 2 Open a discussion | | |
| 3 One open per item | | |
| 4 Comments | | |
| 5 Positions | | |
| 6 The proposal | | |
| 7 The Mediator | | |
| 8 Deciding: checks | | |
| 9 Stale proposal | | |
| 10 Deciding and closing | | |
| 11 Rejection, withdrawal, new item | | |
| 12 Transfer and reassign | | |
| 13 Inbox | | |
| 14 Notifications | | |
| 15 Live updates | | |
| 16 Work queue link | | |
