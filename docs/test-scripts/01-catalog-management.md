# Test script 1: catalog management

Manual script for the catalog screens (M5) using the **example catalog** (`catalog/`, fictional).
Spec: `docs/features/catalog-maintenance.md`. Run it top to bottom on a fresh database: later
steps use what earlier ones create. Each step has an action and an **Expected** result; mark
each one pass or fail and note what you saw when it fails.

Next scripts (not written yet): consultations, discussions.

## 0. Preparation

| | |
|---|---|
| App | `http://127.0.0.1:8090` (see the README for ports) |
| Accounts | Admin, Bea (architect) and Una (plain user), created as described in `00-accounts.md` (Bea is needed for steps 11 and 17, Una for step 17) |
| Browser | two profiles or one normal and one private window, for the concurrent steps |

The LLM is **not** needed for this script (only guided capture uses it, and that is script 2).

## 1. Empty catalog

1. Sign in as the admin and open **Catalog**.
2. **Expected:** the title "The catalog is empty" with three choices: *Import a starter pack*,
   *Create the first building block*, *Start an interview*. No health strip with numbers.

## 2. Import the example catalog

1. Open **Import and export**. Under *Starter packs* find "Example catalog (fictional)".
   **Expected:** it shows 18 building blocks, 12 solutions and 17 rules (the counts the page
   prints; compare them with `catalog/abbs.yaml`, `sbbs.yaml`, `rules.yaml`).
2. Choose *Preview import*.
   **Expected:** "Preview: nothing is written yet", every item under *New items*, nothing
   changed, and the line "Everything imported is saved as proposed, never as validated."
3. Open **Catalog** in another tab.
   **Expected:** still empty. The preview wrote nothing.
4. Back in the preview, choose *Import these items*.
   **Expected:** "Import applied" and a *Back to the catalog* link.
5. Repeat steps 2 and 4 with the same pack.
   **Expected:** the preview now shows the items as *Unchanged* and nothing new.

## 3. Health strip and lists

1. Open **Catalog**.
   **Expected:** the health strip shows all items as **Proposed** (none validated, none draft)
   and a number for *Building blocks without a solution* (9 for the example catalog, for example
   `channel-abstraction`, `template-management`, `delivery-log`). Each number is a link.
2. Follow the gaps link.
   **Expected:** the ABB list opens already filtered to *No solution yet*.
3. In **Building blocks**, search for `sms`. **Expected:** `channel-sms` is listed.
4. Clear the search and filter by domain `security`.
   **Expected:** `audit-log`, `partner-identity` and `secrets-management`. The count line says
   "Showing 3 of N".
5. Open **Solutions**.
   **Expected:** listed alphabetically by id (`consent-platform`, `email-service-x`, ...),
   with their catalog state as text. There is no sort by quality and no score.

## 4. Item page: `channel-sms`

1. Open **Building blocks** and then `channel-sms`.
2. **Expected, header:** name "Channel: SMS", id, a *Proposed* badge, version 1.
3. **Expected, content:** description "Sending text messages to mobile numbers.", domain
   `integration`, recognition hints "SMS" and "text message".
4. **Expected, connections:** `sms-provider-a`, `sms-provider-b`, `sms-provider-c` as
   solutions; the rules that read it in a condition (R-001, R-002, R-003, R-004, R-006, R-007,
   R-009); every entry is a link. Follow `sms-provider-b` and come back.
5. **Expected, usage:** 0 consultations, nothing flagged.
6. **Expected, history:** one row, version 1, origin "Imported".
7. Open `sms-provider-b`.
   **Expected:** state shown as *prohibited*, with its reason. It stays in the list; it is
   excluded, not ranked.

## 5. Validate

1. On `channel-sms` choose *Validate*.
   **Expected:** the badge becomes *Validated*. History shows who validated and when.
2. Validate `channel-email` too (same way). In **Catalog** the health counts move by two.

## 6. Edit an ABB and the "pending version" rule

1. On `channel-sms` choose *Edit*. Change the description to
   `Sending text messages to mobile numbers, including one-time codes.`
2. Fill *What changed and why* with `Mention one-time codes`.
3. Use *Preview impact* before saving.
   **Expected:** "Items that refer to this one" with 10 (7 rules and 3 solutions), "No reference cases
   are pinned.", and the note that a validated version stays in use until the new one is
   validated.
4. Choose *Save as proposed*.
   **Expected:** the item page shows "Version 2 is waiting; the version above stays in use until
   it is validated." and the content above is still the **old** description.
5. Open the history. **Expected:** two rows. Use *Show changes* on version 2: the readable diff
   states that the description changed from the old to the new text (text, not colour alone).
6. Validate version 2. **Expected:** the content now shows the new description, no pending
   notice.

## 7. Rule editor and *Try it*

1. Open **Rules** and then `R-010` (activates `batch-scheduling`, "interaction mode is
   scheduled-batch"), then *Edit*.
2. **Expected:** one test: attribute *interaction_mode* is one of *scheduled-batch*; the
   builder controls are all reachable with the keyboard (Tab through them).
3. In *Try it* set *interaction_mode* to `scheduled-batch` and choose *Try*.
   **Expected:** "Result: true".
4. Set it to `event`. **Expected:** "Result: false".
5. Set it to `unknown`. **Expected:** "Result: indeterminate (an answer is missing)". Unknown is
   never treated as a yes or a no.
6. Leave the editor without saving. **Expected:** the rule is unchanged (version 1 in history).

## 8. Create a solution for a gap

1. Note that `channel-abstraction` has no solution (health strip, step 3).
2. In **Solutions** choose *New*. Fill:
   id `sms-gateway-lib`, name `SMS gateway library`, realises `channel-abstraction`, state
   `recommended`.
3. **Expected:** saving as proposed works; the item page shows it under `channel-abstraction`.
4. In **Catalog** the number of building blocks without a solution is one lower.

## 9. Validator blocks a bad save

1. *New* solution with id `bad id` (a space).
   **Expected:** an inline message next to the field and the save button disabled with the
   reason "Fix the points above to save."
2. Edit `sms-gateway-lib` with *Advanced: edit as JSON*; set `realises` to `no-such-abb` and
   *Apply to the form*.
   **Expected:** a clear message that the building block does not exist, pointing at the field;
   saving is blocked. Set it back to `channel-abstraction`.
3. In rule `R-010` (do not save) set a test on an attribute that does not exist via the JSON
   view. **Expected:** the same kind of blocking message naming the unknown attribute.

## 10. Rule with an exception

1. Create a new rule: id `R-100`, activates `audit-log`, strength `considers`, reason
   `Test rule`.
2. Add a test: *personal_data* is one of `sensitive`. Add an exception ("Except when all of
   these hold"): *regulation* is one of `gdpr`.
3. In *Try it* check these (expected in brackets): personal_data `sensitive`, regulation
   `gdpr` (false); `sensitive`, regulation `health` (true); `none` (false); personal_data
   `sensitive`, regulation `unknown` (indeterminate).
4. Save as draft. **Expected:** badge *Draft*. Drafts do not take part in normal
   consultations.

## 11. Concurrent edit

1. As the admin open `sms-gateway-lib` for editing and change *Limitations*, but do not save.
2. As Bea (second window) open the same item, change *Owner* to `Team Bea`, save.
3. Back as the admin, save.
   **Expected:** "Someone saved version 2 while you were editing. Your text is kept." with the
   two choices *Keep my changes and continue* and *Use their version instead*. Nothing typed is
   lost.
4. Choose *Keep my changes and continue* and save.
   **Expected:** a version 3 exists; history shows both authors.

## 12. History and restore

1. On `sms-gateway-lib` open the history and *Restore* version 1.
2. **Expected:** a **new** version (4) is created with origin "Restored"; versions 1 to 3 remain.
   The content equals version 1.

## 13. Archive

1. Open `channel-sms` and look for *Archive*.
   **Expected:** blocked: "N items still use this, so it cannot be archived yet. Change them
   first."
2. Open `sms-gateway-lib` and choose *Archive this item*, confirm.
   **Expected:** the item shows *Archived*, history stays, and it no longer appears in the
   default list. The gap counter goes back up by one.

## 14. Vocabulary

1. Open **Vocabulary**. **Expected:** attributes, characteristics and lenses are listed (11
   lenses).
2. Open attribute `volume` and change the label of the value `medium` to `Medium-sized`.
   **Expected:** a new version; rules and solutions are not changed or re-versioned.
3. Try to archive the value `scheduled-batch` of `interaction_mode`.
   **Expected:** refused, listing the rules that use it (R-010 and R-011).

## 15. Export and round trip

1. In **Import and export** choose *Export* (YAML).
   **Expected:** a file with the effective catalog, the same shape as `catalog/*.yaml`.
2. Open the file in an editor and change the name of `audit-log` to `Audit trail`.
3. Import the edited file.
   **Expected:** the preview says one item *changed* (and lists the others as unchanged), new
   items are zero; apply it. `audit-log` has a new version, status *Proposed* (not validated,
   even though it was before).
4. Import a file with an invalid reference (for example an SBB with `realises: nope`).
   **Expected:** the errors are listed per item and *Import these items* is blocked: "Fix the
   errors above before importing."

## 16. Work queue (empty state and shape)

1. **Catalog** work queue. **Expected:** it lists "Waiting for validation" for the proposed
   items, and "Drafts to review" if any exist (`R-100`). Gaps and feedback appear only after
   consultations (script 2).
2. Choose *I'll handle this* on one entry.
   **Expected:** it shows "Claimed by <you>", a *Renew claim* and a *Release* button, and
   *Open* goes to the item.
3. Choose *Release*. **Expected:** the entry returns to the queue.
4. Choose *Dismiss*, give no reason. **Expected:** it asks for the reason; with one, the entry
   leaves the queue.

## 17. Roles

1. As **Bea** (architect): everything above is available.
2. As the plain **user**: **Catalog** opens read-only. **Expected:** no *New*, *Edit*,
   *Validate*, *Archive*, no work queue actions and no import. Opening `/catalog/abbs/new`
   directly is refused or redirects.
3. Signed out: any catalog address redirects to sign in.

## Result sheet

| Step | Pass | Notes |
|---|---|---|
| 1 Empty catalog | | |
| 2 Import | | |
| 3 Health and lists | | |
| 4 Item page | | |
| 5 Validate | | |
| 6 Edit and pending version | | |
| 7 Rule editor, Try it | | |
| 8 Solution for a gap | | |
| 9 Validator blocks | | |
| 10 Rule with exception | | |
| 11 Concurrent edit | | |
| 12 History and restore | | |
| 13 Archive | | |
| 14 Vocabulary | | |
| 15 Export and round trip | | |
| 16 Work queue | | |
| 17 Roles | | |
