/** Shapes of the HTTP API (docs/api.md). Kept in one place so the pages stay thin. */

export type Role = 'user' | 'architect' | 'admin';
export type Status = 'draft' | 'proposed' | 'validated';
export type Coverage = 'covered' | 'conditional' | 'blocked' | 'gap';
export type Activation = 'identified' | 'confirmed' | 'potential';
export type SbbResultKind = 'eligible' | 'conditional' | 'excluded';
export type SbbState = 'recommended' | 'accepted' | 'deprecating' | 'prohibited';
export type FactSource = 'stated' | 'inferred' | 'answered' | 'edited';
export type DetailLevel = 'summary' | 'detailed';
export type ThemePreference = 'system' | 'light' | 'dark';

export interface User {
  id: number;
  email: string;
  display_name: string;
  role: Role;
  active: boolean;
  must_change_password: boolean;
}

export interface SessionInfo {
  user: User;
  csrf_token: string;
}

export interface Preferences {
  detail_level: DetailLevel;
  locale: string;
  theme: ThemePreference;
}

export interface TraceTest {
  test: string;
  result: boolean | null;
  attribute: string | null;
  value: string | string[] | null;
  source: string | null;
  children: TraceTest[];
}

export interface RuleEvidence {
  rule: string;
  result: boolean | null;
  strength: 'requires' | 'considers';
  status: Status;
  reason: string;
  tests: TraceTest[];
}

export interface SbbOutcome {
  id: string;
  name: string;
  state: SbbState;
  status: Status;
  result: SbbResultKind;
  exclusion: 'prohibited' | 'not_applies_when' | 'applies_when_not_met' | null;
  reason: string;
  notes: string[];
  tests: TraceTest[];
}

export interface AbbResult {
  id: string;
  activation: Activation;
  strength: 'requires' | 'considers' | null;
  validation: Status | null;
  origin: RuleEvidence[];
  coverage: Coverage;
  sbbs: SbbOutcome[];
}

export interface PendingQuestion {
  attribute: string;
  question: string;
  values: string[];
  multi: boolean;
  impact: string[];
}

export interface EngineResult {
  abbs: AbbResult[];
  pending_questions: PendingQuestion[];
}

export interface TraceEntry {
  ref: string;
  kind: 'abb' | 'rule' | 'sbb' | 'question';
  abb: string | null;
  text: string;
  names: string[];
}

export interface Fact {
  value: string | string[];
  source: FactSource;
  span: string;
}

export interface IdentifiedAbb {
  id: string;
  span: string;
}

export interface Sentence {
  text: string;
  refs: string[];
  verified: boolean;
  problems?: string[];
}

export interface Rationale {
  id: number;
  evaluation_id: number;
  status: 'ok' | 'warnings' | 'failed';
  content: { detail: DetailLevel; sentences: Sentence[] };
  checker: { unverified?: number; problems?: { sentence: number; problems: string[] }[] };
  created_at: string;
  outdated: boolean;
}

export interface CatalogAbb {
  id: string;
  name: string;
  domain: string;
  cross_cutting: boolean;
  description: string;
  does_not_apply_when: string;
  status: Status;
}

export interface CatalogSbb {
  id: string;
  realises: string;
  name: string;
  when_to_choose: string;
  limitations: string;
  characteristics: Record<string, string>;
  owner: string;
}

export interface CatalogAttribute {
  id: string;
  question: string;
  values: string[];
  multi: boolean;
}

export interface ChoiceRecord {
  id: number;
  abb: string;
  kind: 'chosen' | 'decide_later' | 'outside_catalog';
  sbb: string | null;
  sbb_result: 'eligible' | 'conditional' | null;
  sbb_state: SbbState | null;
  reason: string;
  unresolved_questions: string[];
  evaluation_id: number;
  actor: string;
  at: string;
}

export interface FeedbackItem {
  id: number;
  kind: 'missing' | 'wrong';
  abb: string | null;
  text: string;
  author: string;
  at: string;
}

export interface Consultation {
  id: number;
  title: string;
  owner: string;
  revision: { number: number; requirement_text: string; unrecognised: boolean };
  latest_revision: number;
  revisions: { number: number; created_at: string }[];
  identified_abbs: IdentifiedAbb[];
  facts: Record<string, Fact>;
  answered_unknown: string[];
  catalog: {
    abbs: CatalogAbb[];
    sbbs: CatalogSbb[];
    attributes: CatalogAttribute[];
  };
  evaluation: {
    id: number;
    snapshot_id: number;
    trigger: string;
    at: string;
    result: EngineResult;
    trace: TraceEntry[];
  } | null;
  rationale: Rationale | null;
  choices: ChoiceRecord[];
  feedback: FeedbackItem[];
  pinned: { id: number; title: string; pinned_by: string; pinned_at: string } | null;
}

export interface ConsultationListItem {
  id: number;
  title: string;
  created_at: string;
  owner: string;
  revisions: number;
}

/** An error returned by the API in the `{code, message}` shape. */
export interface ApiProblem {
  status: number;
  code: string;
  message: string;
  problems?: string[];
  /** the rest of the error body (e.g. `discussion_id`, the missing positions) */
  detail?: Record<string, unknown>;
}

export type StageName = 'interpreting' | 'checking' | 'evaluating' | 'writing';
