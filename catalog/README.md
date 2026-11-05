# Example catalog

Files describe a **fictional** catalog used by the M1 loader, the validator and
`scenarios/`. The same shapes are what YAML/JSON import and export use.

| File | Content |
|---|---|
| `attributes.yaml` | Core and extension attributes, values, questions, `ask_if`, `applies_to_abbs` |
| `characteristics.yaml` | Small vocabulary used to describe SBBs (comparison, never ranking) |
| `lenses.yaml` | 11 lenses; the lens owns the link to attributes (`feeds_attributes`) |
| `abbs.yaml` | ABBs, with `recognition` hints and the `cross_cutting` flag |
| `sbbs.yaml` | SBBs; each realises one ABB; `state` is a label, `prohibited` excludes |
| `rules.yaml` | Activation rules (condition -> ABB, `requires` / `considers`) |

Conventions
- Items are referenced by **slug** (immutable). In the database they become item ids.
- A missing `status` means `validated` **for the file loader** (M1, tests). Import
  into the database always lands items as `proposed` (`docs/data-model.md` 9).
- Value keys of attributes and characteristics are immutable; labels may change.
- Mapping to the database: `recognition` -> `abb_hints`; `applies_to_abbs` ->
  `attribute_scopes`; `feeds_attributes` -> `lens_feeds`; `typical_dependencies`
  -> `lens_typical_abbs`; `when` / `applies_when` / `not_applies_when` / `ask_if`
  -> `conditions` + tests.
- `scenarios/` documents the expected engine output for this catalog.
