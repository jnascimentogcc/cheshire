# Cheshire web (M4)

Angular (standalone components, signals, `OnPush`), Tailwind CSS 4 mapped onto the tokens
of `docs/ui-spec.md` section 3.2 (`src/styles.css` is where they live), Transloco (English
is the default; another language is another file in `public/i18n/`), `marked` + DOMPurify
for Markdown, self-hosted DM Sans and IBM Plex Mono, Vitest, Prettier.

```bash
npm ci
npm run format:check
npm test                                  # Vitest through the Angular builder
npx ng build --configuration production
npx ng serve                              # http://localhost:4200, /api -> 127.0.0.1:8000
```

## Layout

```
src/app/core/      api (CSRF, error mapping), auth, preferences (theme/detail), SSE reader
src/app/shared/    badges, problem notice, Markdown sanitiser
src/app/consult/   list, new, store (state of the session page), pure logic (+ specs)
src/app/consult/session/   the page and one component per region of consult.md section 3
public/i18n/en.json        every string; a spec checks that every key used exists
```

## Decisions and deviations to confirm

- **SpartanNG.** `ui-spec.md` says to reuse SpartanNG first. The Helm generator was not
  run: the shared pieces here (buttons, badges, cards, form fields, the trace dialog) are
  small, token-based and use native elements (`<dialog>`, `<fieldset>`, `<details>`), which
  gives focus trap, Escape and focus return without a headless library. Adopting
  `@spartan-ng/brain` for menus and comboboxes is open for M5, where the catalog UI needs them.
- **Streaming.** The session page reads the analysis stages from SSE with `fetch` (a POST
  with the CSRF header; `EventSource` cannot do that). The first rationale arrives whole,
  after the checker (see `docs/api.md`).
- **CSP.** nginx sends `script-src 'self'`; styles allow `'unsafe-inline'` because Angular
  component styles are inline. The theme is applied by `public/theme-init.js` (an external
  file) before the first paint.
- **Accessibility.** Recomputation is announced in a polite live region and focus moves to
  the next open question; every badge carries text; the "Why?" trace is a modal `<dialog>`
  with the same content as plain text. Not yet checked with a screen reader or an automated
  audit (axe); that is worth doing before a release.

## Catalog screens (M5)

`src/app/catalog/`: home (health strip, work queue with claim/renew/release/dismiss), lists with
search and filters, the item page (content, connections, usage, history table with readable
diffs, restore, validate, archive, discussions), the editor (structured forms for
ABBs, SBBs and rules; JSON as the advanced path for every kind; condition builder; *Try it*;
impact preview; stale-save handling that keeps what was typed), reference cases, import/export
with starter packs and a dry-run first, and the guided-capture interview. Architect-only routes
use the `requireArchitect` guard; everyone else gets the read-only catalog.

Deviations and open points:

- The condition builder and menus use native `<select>`/checkboxes, not SpartanNG brain
  (still undecided, see above); fully keyboard operable but not audited with a screen reader.
- The *YAML view* of the spec is a JSON view (the API speaks both; JSON needs no parser in the
  browser). Vocabulary kinds (attributes, characteristics, lenses) are edited through it.
- The interview is request/response, not streamed; progress is a "reading your answer" status.
- Some labels in the lists (detail column) and save-blocker messages are English literals, not
  yet in `en.json`.

## Discussion screens (M6)

`src/app/discussions/`: inbox (tabs, filters), new discussion, the discussion page (proposal
editor, impact radius, mediator, thread, positions, decision with a confirmation `<dialog>`,
transfer/reassign, position history; polled every 20 s with a polite announcer) and the
notification bell and page. Item pages show decision summaries and start/join buttons.

Deviations and open points:

- The proposal editor is JSON; the structured forms of M5 are not reused yet.
- Mentions are picked from a members list, not parsed from the text.
- Decisions are not yet linked from the "Why?" trace of a consultation.
- Not checked with a screen reader or on a phone-width layout.
