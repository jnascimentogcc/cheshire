/** Shapes of the catalog maintenance API (docs/api.md, "Catalog maintenance (M5)"). */
import type { Status } from '../core/models';

export type Kind = 'abb' | 'sbb' | 'rule' | 'attribute' | 'characteristic' | 'lens';

/** URL segment -> API kind. The URLs follow catalog-maintenance.md section 2. */
export const KIND_OF_ROUTE: Record<string, Kind> = {
  abbs: 'abb',
  sbbs: 'sbb',
  rules: 'rule',
  attributes: 'attribute',
  characteristics: 'characteristic',
  lenses: 'lens',
};

export const ROUTE_OF_KIND: Record<Kind, string> = {
  abb: 'abbs',
  sbb: 'sbbs',
  rule: 'rules',
  attribute: 'attributes',
  characteristic: 'characteristics',
  lens: 'lenses',
};

export const KINDS: Kind[] = ['abb', 'sbb', 'rule', 'attribute', 'characteristic', 'lens'];

/** A condition in the open format: attribute -> allowed values, plus `abb_present`/`except`. */
export interface RawCondition {
  [key: string]: string[] | RawCondition;
}

export type RawItem = Record<string, unknown> & { id: string };

export interface Health {
  items_by_status: Record<Status, number>;
  abbs_without_sbb: string[];
  validator_errors: number;
  validator_warnings: number;
  queue: Record<WorkKind, number>;
  empty: boolean;
}

export type WorkKind =
  'gap' | 'unrecognised' | 'feedback' | 'draft_review' | 'validation_backlog' | 'validator_finding';

export interface WorkItem {
  id: number;
  kind: WorkKind;
  status: 'open' | 'claimed' | 'done' | 'dismissed';
  payload: Record<string, string | number | null>;
  subject: string | null;
  subject_kind: Kind | null;
  sessions: number;
  first_consultation_id: number | null;
  claimed_by: string | null;
  claimed_by_me: boolean;
  claim_expires_at: string | null;
  expiring_soon: boolean;
  resolution: string;
  created_at: string;
}

export interface TableRow {
  slug: string;
  archived: boolean;
  effective_number: number | null;
  effective_status: Status | null;
  latest_number: number;
  latest_status: Status;
  facts: Record<string, string | number | boolean>;
  consultations: number;
  corrections: number;
  sbbs?: number;
}

export interface VersionRow {
  number: number;
  status: Status;
  created_at: string;
  change_note: string;
  origin: string;
  author: string | null;
  validated_by: string | null;
  validated_at: string | null;
}

export interface ItemResponse {
  item: RawItem;
  versions: VersionRow[];
}

export interface Connection {
  kind: Kind;
  slug: string;
  ref_kind: string;
}

export interface Usage {
  consultations: number;
  last_used: string | null;
  flagged: number;
  corrected: number;
  chosen: number;
}

export interface Change {
  path: string;
  kind: 'added' | 'removed' | 'changed';
  text: string;
}

export interface Difference {
  label: 'added' | 'removed' | 'changed' | 'question';
  text: string;
}

export interface Impact {
  effective_now: boolean;
  dependents: Connection[];
  new_issues: string[];
  reference_cases: {
    id: number;
    title: string;
    consultation_id: number;
    error: string;
    already_differs: boolean;
    differences: Difference[];
  }[];
  recent_consultations: {
    consultation_id: number;
    title: string;
    error: string;
    differences: Difference[];
  }[];
}

export interface TryResult {
  outcome: 'true' | 'false' | 'indeterminate';
  text: string[];
  unknown_attributes: string[];
}

export interface Vocabulary {
  attributes: { id: string; values: string[]; multi?: boolean; question?: string }[];
  abbs: { id: string; name: string }[];
  characteristics: { id: string; values: string[] }[];
}

export interface ImportReport {
  created: Record<string, string[]>;
  changed: Record<string, string[]>;
  unchanged: Record<string, string[]>;
  absent: Record<string, string[]>;
  issues: string[];
  blocking: boolean;
  batch_id: number | null;
}

export interface StarterPack {
  name: string;
  title: string;
  description: string;
  counts: Record<string, number>;
}

export interface InterviewMessage {
  id: number;
  seq: number;
  role: 'user' | 'assistant';
  text: string;
  lens: string | null;
}

export interface Suggestion {
  id: number;
  kind: 'sbb' | 'rule' | 'abb' | 'attribute_value';
  payload: {
    item?: RawItem;
    attribute?: string;
    value?: string;
    quote: string;
    why: string;
  };
  status: 'pending' | 'accepted' | 'rejected' | 'depends';
  follow_up: string;
  decided_by: string | null;
  resulting_kind: Kind | null;
  resulting_item: string | null;
  resulting_version: number | null;
}

export interface Interview {
  id: number;
  status: 'open' | 'closed';
  subject: string | null;
  started_by: string;
  messages: InterviewMessage[];
  suggestions: Suggestion[];
  needs_retry: boolean;
  finished: boolean;
  progress: { answered: number; total: number };
}

export interface ReferenceCase {
  id: number;
  title: string;
  consultation_id: number;
  pinned_at: string;
  pinned_by: string;
}
