/** Pure helpers of the discussion screens (no I/O, unit-tested). */
import type { Discussion, Entry, Notification, Position, Stance } from './models';

export interface ResponseDraft {
  accepted: boolean | null;
  response: string;
}

/** Opposing positions are the ones the decider has to answer before deciding. */
export function opposing(positions: Position[]): Position[] {
  return positions.filter((p) => p.stance === 'oppose');
}

/** Names of the opposing positions that still lack an answer (empty = ready to decide). */
export function unanswered(
  positions: Position[],
  drafts: Record<number, ResponseDraft | undefined>,
): string[] {
  return opposing(positions)
    .filter((p) => {
      const d = drafts[p.id];
      return !d || !d.response.trim() || d.accepted === null;
    })
    .map((p) => p.participant);
}

/** What the latest synthesis proposed for the opposing positions, to pre-fill the form. */
export function prefill(thread: Entry[], positions: Position[]): Record<number, ResponseDraft> {
  const live = new Set(opposing(positions).map((p) => p.id));
  const out: Record<number, ResponseDraft> = {};
  const synthesis = [...thread]
    .reverse()
    .find((e) => e.kind === 'mediator' && e.grounding?.mode === 'synthesis');
  for (const r of synthesis?.grounding?.responses ?? []) {
    if (live.has(r.position_id)) {
      out[r.position_id] = { accepted: r.accepted, response: r.response };
    }
  }
  return out;
}

/** The latest synthesis, if any: its draft rationale and suggested change. */
export function latestSynthesis(thread: Entry[]): Entry | null {
  return (
    [...thread].reverse().find((e) => e.kind === 'mediator' && e.grounding?.mode === 'synthesis') ??
    null
  );
}

/** Entries that were not in the previous view (for the polite announcement). */
export function newEntries(before: Discussion | null, after: Discussion): number {
  if (!before) {
    return 0;
  }
  const seen = new Set(before.thread.map((e) => e.id));
  return after.thread.filter((e) => !seen.has(e.id)).length;
}

/** `kind:slug` mentions in a text become catalog links. */
export function catalogRefs(text: string): { text: string; link: string[] | null }[] {
  const route: Record<string, string> = {
    abb: 'abbs',
    sbb: 'sbbs',
    rule: 'rules',
    attribute: 'attributes',
    characteristic: 'characteristics',
    lens: 'lenses',
  };
  const out: { text: string; link: string[] | null }[] = [];
  let last = 0;
  for (const m of text.matchAll(
    /\b(abb|sbb|rule|attribute|characteristic|lens):([A-Za-z0-9](?:[A-Za-z0-9_.-]*[A-Za-z0-9])?)/g,
  )) {
    const index = m.index ?? 0;
    if (index > last) {
      out.push({ text: text.slice(last, index), link: null });
    }
    out.push({ text: m[0], link: ['/catalog', route[m[1]], m[2]] });
    last = index + m[0].length;
  }
  if (last < text.length) {
    out.push({ text: text.slice(last), link: null });
  }
  return out;
}

/** Where a notification leads. */
export function notificationLink(n: Notification): string[] {
  return n.subject_type === 'discussion' ? ['/discussions', String(n.subject_id)] : ['/catalog'];
}

export function stanceNeedsReason(stance: Stance): boolean {
  return stance === 'oppose' || stance === 'support_with_conditions';
}

/** The proposal as the editor shows it: formatted JSON. */
export function proposalText(item: object): string {
  return JSON.stringify(item, null, 2);
}

export function parseProposal(text: string): {
  item: Record<string, unknown> | null;
  error: string;
} {
  try {
    const value: unknown = JSON.parse(text);
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      return { item: value as Record<string, unknown>, error: '' };
    }
    return { item: null, error: 'not_object' };
  } catch {
    return { item: null, error: 'not_json' };
  }
}
