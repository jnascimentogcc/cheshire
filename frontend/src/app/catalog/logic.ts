/** Pure helpers of the catalog screens (unit-tested in logic.spec.ts). */
import type { RawCondition, Vocabulary, WorkItem } from './models';

export interface ConditionTest {
  attribute: string;
  values: string[];
}

/** A condition split into the three kinds of row the builder shows (rule-language.md 2). */
export interface ConditionRows {
  tests: ConditionTest[];
  abbs: string[];
  except: ConditionRows | null;
}

export function toRows(raw: RawCondition | undefined): ConditionRows {
  const rows: ConditionRows = { tests: [], abbs: [], except: null };
  for (const [key, value] of Object.entries(raw ?? {})) {
    if (key === 'abb_present') {
      rows.abbs = [...(value as string[])];
    } else if (key === 'except') {
      rows.except = toRows(value as RawCondition);
    } else {
      rows.tests.push({ attribute: key, values: [...(value as string[])] });
    }
  }
  return rows;
}

/** Empty tests are dropped; an empty condition is `{}` (always true). */
export function fromRows(rows: ConditionRows): RawCondition {
  const raw: RawCondition = {};
  for (const t of rows.tests) {
    if (t.attribute && t.values.length > 0) {
      raw[t.attribute] = [...t.values];
    }
  }
  if (rows.abbs.length > 0) {
    raw['abb_present'] = [...rows.abbs];
  }
  if (rows.except) {
    const inner = fromRows(rows.except);
    if (Object.keys(inner).length > 0) {
      raw['except'] = inner;
    }
  }
  return raw;
}

/** Attributes and ABBs a condition reads, for the Try-it panel. */
export function referencedIn(rows: ConditionRows): { attributes: string[]; abbs: string[] } {
  const attributes = new Set<string>();
  const abbs = new Set<string>();
  for (let r: ConditionRows | null = rows; r; r = r.except) {
    r.tests.forEach((t) => t.attribute && attributes.add(t.attribute));
    r.abbs.forEach((a) => abbs.add(a));
  }
  return { attributes: [...attributes].sort(), abbs: [...abbs].sort() };
}

/** Problems a person can fix before saving; the server checks again (invariant 5). */
export function conditionProblems(rows: ConditionRows, vocab: Vocabulary): string[] {
  const problems: string[] = [];
  const abbIds = new Set(vocab.abbs.map((a) => a.id));
  for (let r: ConditionRows | null = rows; r; r = r.except) {
    for (const t of r.tests) {
      const attr = vocab.attributes.find((a) => a.id === t.attribute);
      if (!attr) {
        problems.push(`unknown attribute ${t.attribute}`);
      } else {
        t.values
          .filter((v) => !attr.values.includes(v))
          .forEach((v) => problems.push(`${t.attribute} has no value ${v}`));
      }
    }
    r.abbs.filter((a) => !abbIds.has(a)).forEach((a) => problems.push(`unknown ABB ${a}`));
  }
  return problems;
}

/** Where an architect goes to handle a work-queue entry (catalog-maintenance.md section 3). */
export function workTarget(
  item: WorkItem,
): { link: string[]; query?: Record<string, string> } | null {
  switch (item.kind) {
    case 'gap':
      return item.subject
        ? { link: ['/catalog', 'sbbs', 'new'], query: { realises: item.subject } }
        : null;
    case 'feedback':
      return item.subject ? { link: ['/catalog', 'abbs', item.subject] } : null;
    case 'draft_review':
    case 'validation_backlog': {
      const kind = String(item.payload['item_kind'] ?? '');
      const route = ({ abb: 'abbs', sbb: 'sbbs', rule: 'rules' } as Record<string, string>)[kind];
      return route && item.payload['item']
        ? { link: ['/catalog', route, String(item.payload['item'])] }
        : null;
    }
    case 'unrecognised':
      return item.first_consultation_id
        ? { link: ['/consult', String(item.first_consultation_id)] }
        : null;
    default:
      return null;
  }
}

/**
 * What "Open" shows. It is the thing the entry is about, not the place where work starts:
 * for a gap that is the building block itself. Claiming an entry goes to the same place.
 */
export function openTarget(
  item: WorkItem,
): { link: string[]; query?: Record<string, string> } | null {
  if (item.kind === 'gap') {
    return item.subject ? { link: ['/catalog', 'abbs', item.subject] } : null;
  }
  return workTarget(item);
}

/** True when a new id would break the slug rule of catalog_items. */
export function validSlug(slug: string): boolean {
  return /^[A-Za-z0-9][A-Za-z0-9_.-]*$/.test(slug);
}
