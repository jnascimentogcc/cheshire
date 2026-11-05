import type {
  AbbResult,
  CatalogSbb,
  Consultation,
  EngineResult,
  PendingQuestion,
  SbbOutcome,
  TraceEntry,
  TraceTest,
} from '../core/models';

/** ABB groups of the session page, in display order (consult.md 3, region 5). */
export type AbbGroup = 'required' | 'consider' | 'identified' | 'potential';
export const GROUP_ORDER: AbbGroup[] = ['required', 'consider', 'identified', 'potential'];

export function groupOf(abb: AbbResult): AbbGroup {
  if (abb.activation === 'identified') {
    return 'identified';
  }
  if (abb.activation === 'potential') {
    return 'potential';
  }
  return abb.strength === 'considers' ? 'consider' : 'required';
}

/** ABBs per group; inside a group the engine's order (alphabetical by id) is kept. */
export function groupAbbs(result: EngineResult): { group: AbbGroup; abbs: AbbResult[] }[] {
  return GROUP_ORDER.map((group) => ({
    group,
    abbs: result.abbs.filter((abb) => groupOf(abb) === group),
  })).filter((g) => g.abbs.length > 0);
}

export interface Summary {
  required: number;
  consider: number;
  identified: number;
  potential: number;
  covered: number;
  conditional: number;
  blocked: number;
  gaps: number;
  questions: number;
}

export function summarize(result: EngineResult): Summary {
  const count = (pick: (abb: AbbResult) => boolean): number => result.abbs.filter(pick).length;
  return {
    required: count((a) => groupOf(a) === 'required'),
    consider: count((a) => groupOf(a) === 'consider'),
    identified: count((a) => groupOf(a) === 'identified'),
    potential: count((a) => groupOf(a) === 'potential'),
    covered: count((a) => a.coverage === 'covered'),
    conditional: count((a) => a.coverage === 'conditional'),
    blocked: count((a) => a.coverage === 'blocked'),
    gaps: count((a) => a.coverage === 'gap'),
    questions: result.pending_questions.length,
  };
}

/** "N of M rules are not yet validated": rules the result rests on (invariant 8). */
export function ruleValidation(result: EngineResult): { total: number; notValidated: number } {
  const rules = new Map<string, boolean>();
  for (const abb of result.abbs) {
    for (const evidence of abb.origin) {
      rules.set(`${abb.id}:${evidence.rule}`, evidence.status === 'validated');
    }
  }
  return { total: rules.size, notValidated: [...rules.values()].filter((ok) => !ok).length };
}

/** SBBs of an ABB in the stable neutral order: alphabetical by id (invariant 2). */
export function sbbsByResult(abb: AbbResult, result: SbbOutcome['result']): SbbOutcome[] {
  return abb.sbbs.filter((s) => s.result === result).sort((a, b) => a.id.localeCompare(b.id));
}

/** Questions (attributes) the engine could not decide for this ABB. */
export function openQuestionsFor(result: EngineResult, abbId: string): PendingQuestion[] {
  return result.pending_questions.filter((q) => q.impact.includes(abbId));
}

function unknownAttributes(tests: TraceTest[], into: Set<string>): void {
  for (const test of tests) {
    if (test.result === null && test.attribute) {
      into.add(test.attribute);
    }
    unknownAttributes(test.children, into);
  }
}

/** The answers that would resolve a conditional SBB: the attributes behind unknown tests. */
export function missingAnswers(sbb: SbbOutcome): string[] {
  const found = new Set<string>();
  unknownAttributes(sbb.tests, found);
  return [...found].sort();
}

/** Facts as table rows: the attributes of the result, alphabetical, with unknown last. */
export interface FactRow {
  attribute: string;
  value: string[];
  source: 'stated' | 'inferred' | 'answered' | 'edited' | 'unknown';
  span: string;
}

export function factRows(view: Consultation): FactRow[] {
  const rows: FactRow[] = Object.entries(view.facts).map(([attribute, fact]) => ({
    attribute,
    value: Array.isArray(fact.value) ? fact.value : [fact.value],
    source: fact.source,
    span: fact.span,
  }));
  for (const attribute of view.answered_unknown) {
    rows.push({ attribute, value: [], source: 'unknown', span: '' });
  }
  return rows.sort((a, b) => a.attribute.localeCompare(b.attribute));
}

/** ABBs that have two or more eligible or conditional SBBs: the comparison region. */
export function comparable(result: EngineResult): AbbResult[] {
  return result.abbs.filter((abb) => abb.sbbs.filter((s) => s.result !== 'excluded').length >= 2);
}

export interface ComparisonTable {
  columns: SbbOutcome[];
  details: Map<string, CatalogSbb>;
  characteristics: string[];
}

/** Side-by-side facts for one ABB; columns alphabetical, no ordering by quality. */
export function comparisonTable(abb: AbbResult, sbbs: CatalogSbb[]): ComparisonTable {
  const columns = abb.sbbs
    .filter((s) => s.result !== 'excluded')
    .sort((a, b) => a.id.localeCompare(b.id));
  const details = new Map(sbbs.map((s) => [s.id, s]));
  const names = new Set<string>();
  for (const column of columns) {
    for (const key of Object.keys(details.get(column.id)?.characteristics ?? {})) {
      names.add(key);
    }
  }
  return { columns, details, characteristics: [...names].sort() };
}

/** Trace entries that belong to one ABB (its rules and SBBs), for the "Why?" panel. */
export function entriesFor(trace: TraceEntry[], abbId: string): TraceEntry[] {
  return trace.filter((e) => e.abb === abbId);
}

export function entryByRef(trace: TraceEntry[], ref: string): TraceEntry | undefined {
  return trace.find((e) => e.ref === ref);
}

/** Plain text of a trace entry list, for keyboard users and copy/paste. */
export function traceAsText(entries: TraceEntry[]): string {
  return entries.map((e) => `[${e.ref}]\n${e.text}`).join('\n\n');
}

// --- requirement text with the spans the Interpreter used ---------------------------------

export interface SpanSource {
  /** 1-based index chip shown next to the highlight and in the legend. */
  index: number;
  kind: 'abb' | 'attribute';
  id: string;
  text: string;
}

export interface Segment {
  text: string;
  chips: number[];
}

/** One legend entry per span source, numbered in a stable order (ABBs, then attributes). */
export function spanSources(view: Consultation): SpanSource[] {
  const sources: Omit<SpanSource, 'index'>[] = [];
  for (const abb of [...view.identified_abbs].sort((a, b) => a.id.localeCompare(b.id))) {
    if (abb.span) {
      sources.push({ kind: 'abb', id: abb.id, text: abb.span });
    }
  }
  for (const [id, fact] of Object.entries(view.facts).sort(([a], [b]) => a.localeCompare(b))) {
    if (fact.span) {
      sources.push({ kind: 'attribute', id, text: fact.span });
    }
  }
  return sources.map((s, i) => ({ ...s, index: i + 1 }));
}

/** A span may join parts with "..."; each part is located on its own. */
function rangesOf(text: string, span: string): [number, number][] {
  const lower = text.toLowerCase();
  const found: [number, number][] = [];
  for (const part of span
    .split('...')
    .map((p) => p.trim())
    .filter(Boolean)) {
    const at = lower.indexOf(part.toLowerCase());
    if (at >= 0) {
      found.push([at, at + part.length]);
    }
  }
  return found;
}

/** Splits the text so that every span is a segment carrying its chip numbers. Overlapping
 * spans share the overlap, so highlight is never the only cue: the chips say which. */
export function highlightSegments(text: string, sources: SpanSource[]): Segment[] {
  const marks: { start: number; end: number; index: number }[] = [];
  for (const source of sources) {
    for (const [start, end] of rangesOf(text, source.text)) {
      marks.push({ start, end, index: source.index });
    }
  }
  const cuts = new Set<number>([0, text.length]);
  for (const m of marks) {
    cuts.add(m.start);
    cuts.add(m.end);
  }
  const points = [...cuts].sort((a, b) => a - b);
  const segments: Segment[] = [];
  for (let i = 0; i < points.length - 1; i++) {
    const [start, end] = [points[i], points[i + 1]];
    const chips = [
      ...new Set(marks.filter((m) => m.start <= start && m.end >= end).map((m) => m.index)),
    ].sort((a, b) => a - b);
    segments.push({ text: text.slice(start, end), chips });
  }
  return segments;
}
