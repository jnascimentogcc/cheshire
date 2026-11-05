# Test script 2: consultations

Manual script for the consult screens (M3 and M4) using the **example catalog**. Spec:
`docs/features/consult.md`. Expected engine results come from `scenarios/*.yaml`, which are the
acceptance contract for this catalog.

## 0. Preparation

| | |
|---|---|
| App | `http://127.0.0.1:8090` |
| Catalog | the example catalog imported (script 1, step 2). Import lands everything as *proposed*, which is fine: `proposed` items are used and badged |
| Accounts | Admin, Bea and Una, as in `00-accounts.md`. For step 17 you also need a second plain user (invite one more with the same snippet) |
| LLM | `CHESHIRE_LLM_API_KEY` and the model names set in `.env` (Interpreter and Writer are used) |

If you ran script 1 on the same database, its leftovers do not matter here, with one exception:
do not leave `channel-sms`, `R-010` or the `sms-provider-*` items archived or edited in ways that
change their conditions.

**The Interpreter is a language model.** The same sentence may be read slightly differently on
each run (an extra ABB, a different inferred value). The *engine* is exact: for the facts you see
under *What was understood*, the result must match the expectations below. When the model read
something else, fix the facts by hand (step 3) and then compare. Report a difference in the
engine part as a bug, a difference in the reading as a note.

## 1. New consultation form

1. Sign in as the plain **user** and open **Consult**.
   **Expected:** "You have no consultations yet." and a link "Write your first requirement".
2. Open it and choose *Analyze* with an empty text.
   **Expected:** "Write the requirement before analyzing it." Nothing is sent.

## 2. First consultation (shipped order)

1. Name: `Shipped order`. Requirement:
   `When an order is shipped, the customer must receive a notification by e-mail and SMS.`
2. Choose *Analyze*.
   **Expected:** the stages appear in turn: "Reading the requirement", "Checking it against the
   catalog", "Evaluating the rules". The session page opens at `/consult/<id>`.
3. **Expected, building blocks identified from the text:** `notification-orchestration`,
   `channel-email`, `channel-sms`, each with an index chip that matches a marked span of the
   text (the highlight is never the only cue).
4. **Expected, facts:** `interaction_mode = event` and `personal_data = personal`, source
   *Inferred*.
5. **Expected, groups** (from `scenarios/notify-shipped-order.yaml`):
   - *Required*: `failure-handling` (gap), `secrets-management` (covered by `secrets-vault`),
     `event-messaging` (gap).
   - *To consider*: `template-management` (gap), `delivery-log` (gap), `channel-abstraction`
     (gap, badge *Proposed*).
   - *Identified from your text*: `notification-orchestration` (covered, `notification-hub`),
     `channel-email` (covered, `email-service-x`), `channel-sms` (**Conditional**).
   - *Potential (needs an answer)*: `consent-management`.
6. **Expected, `channel-sms`:** `sms-provider-a` and `sms-provider-c` as *Conditional* with the
   question each needs; `sms-provider-b` under *Excluded* as *Prohibited*.
7. **Expected, open questions:** `message_type` first, then `volume`, each showing "Changes:"
   with the affected blocks.
8. **Expected, summary:** counts for required, to consider, covered, conditional, blocked, gaps,
   potential, and a line "N of M rules this result rests on are not yet validated."
9. Gaps show "No solution registered in the catalog for this building block. It was recorded for
   the architects." with the same prominence as the covered blocks.

## 3. Editing what was understood

1. Under *Facts* edit `personal_data`: change `personal` to `none`, then back to `personal`.
   **Expected:** the source becomes *Edited by you* and the result updates at once, with no page
   reload and focus kept where you were.
2. **Expected, after `none`:** `consent-management` disappears from the potential group (rule
   R-001/R-002 need personal data). Back to `personal`: it returns.
3. Under *Building blocks identified* choose *Add a building block*, pick `data-masking`, *Add*.
   **Expected:** it appears marked "identified by you" and has a *Remove* button.
4. Remove it. Then look at `failure-handling`.
   **Expected:** no *Remove* there. The note says blocks the rules add cannot be removed here and
   points to feedback.

## 4. Answering questions

1. Answer `message_type` with `transactional`.
   **Expected:** the answered question leaves *Open questions*; the facts table shows the value
   with source *Answered*; the live region says "1 question left" (check with a screen reader or
   the page's status text); focus stays on the next question.
2. Answer `volume` with `medium`.
   **Expected** (`scenarios/notify-shipped-order-answered.yaml`):
   - `channel-sms` becomes **Covered**, eligible `sms-provider-a` only.
   - Excluded: `sms-provider-b` *Prohibited*, `sms-provider-c` "Its conditions are not met".
   - `consent-management` moves up to *To consider* and is covered by `consent-platform`.
   - "Nothing is waiting for an answer."

## 5. "I don't know" is an answer, not an error

1. Change the `volume` fact to *Unknown* (or answer "I don't know" in a new session).
   **Expected:** `channel-sms` goes back to *Conditional* with the missing answer named. No error
   is shown anywhere. Set `volume` back to `medium` afterwards.

## 6. Sensitive data blocks every SMS solution

1. Edit `personal_data` to `sensitive`.
   **Expected** (`scenarios/notify-sensitive-blocked.yaml`): `channel-sms` is **Blocked**: all
   three providers are excluded, `sms-provider-a` as "Does not apply here". `channel-email` stays
   covered. Blocked is visible, not hidden.
2. Set it back to `personal`.

## 7. The "Why?" trace

1. On `failure-handling` choose *Why?*.
   **Expected:** a dialog with the rule (`R-003`), its reason ("External providers fail; sends
   must be retried safely without duplicates."), each test with its value and source.
2. Press **Escape**.
   **Expected:** it closes and focus returns to the *Why?* button. A plain-text version of the
   same content is available in the dialog.

## 8. Rationale

1. **Expected:** an explanation was generated automatically after the result (region
   *Rationale*), with reference chips such as `abb:channel-sms` after the sentences. If it fails,
   the error stays inside this region and the rest of the page keeps working.
2. Read it against the result. **Expected:**
   - Only blocks and solutions that are in the result are mentioned.
   - Nothing says one solution is better, best or preferred.
   - Open a chip: it opens the matching trace entry.
3. Change an answer (for example `volume` to `high`).
   **Expected:** the notice "Outdated: the answers changed after this was written." appears; the
   text is **not** rewritten by itself.
4. Choose *Update explanation*. **Expected:** the notice goes away and the text matches the new
   facts.
5. Switch *Detail level* to *Detailed*, reload the page.
   **Expected:** it is still *Detailed* (remembered per user); the result itself is the same.
   Switch back to *Summary*.

## 9. Comparison

1. Put the facts back to the state of step 4 but with `volume` unknown, so two SMS providers are
   eligible or conditional.
2. **Expected:** the *Comparison* region has a table for `channel-sms` with columns in
   alphabetical order (`sms-provider-a`, `sms-provider-c`), rows *When to choose* and
   *Limitations* plus the characteristics. The note says nothing ranks the options. There is no
   star, score or "best".

## 10. Record a choice

1. Set `volume` to `medium` again. On `channel-sms` choose `sms-provider-a`, no reason, *Save
   choice*.
   **Expected:** "Recorded:" with your name and the time. No reason was required (eligible).
2. On `notification-orchestration` choose *Decide later* and save. **Expected:** recorded.
3. On `failure-handling` (a gap) choose *Will be handled outside the catalog* and save.
4. Set `volume` to unknown, then try to choose `sms-provider-c` without a reason.
   **Expected:** "This choice is conditional. Still unresolved:" with the question, and "A reason
   is required when the solution is conditional or deprecating." Saving is refused without a
   reason; with one it is accepted and the warning stays visible.
5. `sms-provider-b` is not offered as a choice (it is prohibited).

## 11. Feedback and the work queue

1. On `failure-handling` send feedback: kind *Something is missing*, text
   `We need a retry library recommendation`.
   **Expected:** "Feedback sent" and the note that it goes to the architects' queue.
2. Send one more for *The whole result*, kind *Something is wrong*.
3. As an **architect** open **Catalog**, work queue.
   **Expected:** under *Gaps* the blocks used with no solution (for example `failure-handling`,
   `event-messaging`, `template-management`, `delivery-log`, `channel-abstraction`) with
   "Sessions: 1"; under *Feedback from consultations* the two entries.
4. On a gap choose *Open*. **Expected:** the building block page.

## 12. A requirement nothing matches

1. As the user create a consultation:
   `Water the office plants every Tuesday morning.`
   **Expected:** "No building block in the catalog matched this text. It was recorded as an
   unrecognised requirement for the architects. You can rephrase it below."
2. As an architect, **Catalog**: *Requirements nothing in the catalog matched* lists it, and
   *Open* goes to the consultation.

## 13. Revisions

1. In the shipped-order session choose *Rewrite the requirement*, append
   ` Customers must be able to opt out.`, *Analyze again*.
   **Expected:** a revision 2; revision 1 stays readable.
2. Open revision 1 in the revisions list.
   **Expected:** "You are reading revision 1. The latest is revision 2. Earlier revisions cannot
   be changed." with a *Go to the latest* link; the edit and answer controls are off.

## 14. Second scenario: partner report

1. New consultation: `Export monthly reports to an external partner.`
2. **Expected** (`scenarios/partner-report-export.yaml`):
   - Facts: `interaction_mode = scheduled-batch`, `boundary = external-partner`.
   - `batch-scheduling` covered by `job-scheduler-a`.
   - `secure-file-transfer` covered with two eligible solutions: `managed-file-transfer-b`
     (state *Deprecating*) and `sftp-gateway`.
   - `audit-log` covered (`audit-service`); `secrets-management` covered (`secrets-vault`).
   - Gaps: `report-generation`, `job-monitoring`, `failure-handling`, `partner-identity`,
     `interface-contract-management`.
   - `data-masking` *Potential* and *Conditional* (`masking-tool`).
   - One open question: `personal_data`.
3. Choose `managed-file-transfer-b` without a reason.
   **Expected:** a reason is required because it is deprecating. Saving with a reason works.

## 15. Export

1. In the shipped-order session choose *Download Markdown*.
   **Expected:** a file with Requirement, What was understood, Result, Rationale (one bullet per
   sentence, sources on their own line in code format, no raw `[abb:x]` text) and Choices.
   Solutions are listed alphabetically; no ranking words.
2. Choose *Download JSON*. **Expected:** the same content, valid JSON.
3. Open the Markdown in a previewer. **Expected:** the rationale reads as a list, not one block.

## 16. Reference case

1. As an architect, on the shipped-order session choose *Pin as reference case* with a name.
   **Expected:** "Pinned as ... by ...". It appears in **Catalog > Reference cases**.
2. In **Catalog**, edit `channel-sms` (script 1, step 6) and use *Preview impact*.
   **Expected:** the pinned case is replayed and listed ("No difference." or the differences in
   words). Unpin it afterwards if you do not want it.

## 17. Visibility

1. As the plain **user** open **Consult**: only your own consultations are listed.
2. As Bea (architect): all consultations are listed.
3. As a second plain user, open the first user's `/consult/<id>` directly.
   **Expected:** not found; nothing from the session is shown.

## 18. Provider failure (optional)

Needs a restart of the API with a wrong key, for example
`CHESHIRE_LLM_API_KEY=wrong docker compose up -d api` with the port overrides. Put the right key
back afterwards.

1. Analyze a new requirement.
   **Expected:** a clear error with the text kept and *Try again*; no partial result.
2. Open an existing consultation. **Expected:** the result and facts still work and answers can
   be changed; only the rationale region reports the problem when you ask for an update.

## Result sheet

| Step | Pass | Notes |
|---|---|---|
| 1 Form | | |
| 2 First consultation | | |
| 3 Editing what was understood | | |
| 4 Answering questions | | |
| 5 "I don't know" | | |
| 6 Sensitive data | | |
| 7 Why? trace | | |
| 8 Rationale | | |
| 9 Comparison | | |
| 10 Choices | | |
| 11 Feedback and queue | | |
| 12 Unrecognised requirement | | |
| 13 Revisions | | |
| 14 Partner report | | |
| 15 Export | | |
| 16 Reference case | | |
| 17 Visibility | | |
| 18 Provider failure | | |
