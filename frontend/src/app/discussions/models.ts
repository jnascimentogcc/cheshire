/** Shapes of the discussions API (docs/api.md, "Discussions (M6)"). */
import type { Change, Connection, Difference, Kind, RawItem } from '../catalog/models';

export type Stance = 'support' | 'support_with_conditions' | 'oppose' | 'abstain';
export const STANCES: Stance[] = ['support', 'support_with_conditions', 'oppose', 'abstain'];

export type DiscussionStatus = 'open' | 'accepted' | 'rejected' | 'withdrawn';
export type Outcome = 'accepted' | 'accepted_modified' | 'rejected' | 'withdrawn';
export type EntryKind = 'comment' | 'position' | 'mediator' | 'system';
export type SentenceKind =
  'fact' | 'question' | 'counterargument' | 'suggestion' | 'agreement' | 'disagreement';
export type Tab = 'attention' | 'mine' | 'open' | 'closed' | 'orphaned';

export interface InboxRow {
  id: number;
  title: string;
  status: DiscussionStatus;
  item_kind: Kind;
  item_slug: string;
  opener: string;
  decider: string;
  decider_active: boolean;
  opened_at: string;
  closed_at: string | null;
  last_activity: string;
  participants: number;
  comments: number;
  inactive_days: number;
  i_decide: boolean;
  domain: string;
}

export interface Member {
  id: number;
  name: string;
  role: string;
}

export interface MediatorSentence {
  kind: SentenceKind;
  text: string;
  refs: string[];
}

export interface Grounding {
  mode?: 'brief' | 'ask' | 'challenge' | 'synthesis' | 'detected';
  source?: string;
  asked_by?: number;
  question?: string;
  sentences?: MediatorSentence[];
  facts?: Record<string, string>;
  suggested_change?: string;
  draft_rationale?: string;
  responses?: { position_id: number; accepted: boolean; response: string }[];
  issues?: string[];
}

export interface Entry {
  id: number;
  seq: number;
  kind: EntryKind;
  author_id: number | null;
  author: string | null;
  body: string;
  grounding: Grounding | null;
  ai: boolean;
  created_at: string;
  edited_at: string | null;
  retracted_at: string | null;
  edits: number;
}

export interface Position {
  id: number;
  participant_id: number;
  participant: string;
  stance: Stance;
  reason: string;
  created_at: string;
  revisions: number;
}

export interface PositionHistory {
  id: number;
  participant: string;
  stance: Stance;
  reason: string;
  created_at: string;
  superseded_at: string | null;
}

export interface ImpactContent {
  dependents: Connection[];
  new_issues: string[];
  reference_cases: { id: number; title: string; differences: Difference[]; error: string }[];
  recent_consultations: {
    consultation_id: number;
    title: string;
    differences: Difference[];
    error: string;
  }[];
  usage: { consultations?: number; flagged?: number; corrected?: number; chosen?: number };
  summary: {
    dependents: number;
    reference_cases_changed: number;
    consultations_changed: number;
    new_issues: number;
  };
}

export interface ImpactView {
  current: { id: number; kind: string; content: ImpactContent; computed_at: string } | null;
  opened: { id: number; computed_at: string } | null;
  refreshed?: boolean;
  since_opening: { new: string[]; gone: string[] };
}

export interface ProposalView {
  version: number | null;
  item: RawItem | Record<string, never>;
  base_item: RawItem | Record<string, never>;
  base_version: number | null;
  is_new_item: boolean;
  changes: Change[];
  stale: { latest_version: number; base_version: number; changes: Change[] } | null;
}

export interface DecisionRecord {
  id: number;
  outcome: Outcome;
  rationale: string;
  resulting_status: 'validated' | 'proposed' | null;
  decided_at: string;
  decider: string;
  version: number | null;
  responses: {
    position_id: number;
    accepted: boolean;
    response: string;
    participant: string;
    stance: Stance;
    reason: string;
  }[];
}

export interface Discussion {
  id: number;
  title: string;
  status: DiscussionStatus;
  item: { kind: Kind; slug: string };
  opener: { id: number; name: string };
  decider: { id: number; name: string; active: boolean };
  opened_at: string;
  closed_at: string | null;
  participants: { id: number; name: string; active: boolean; joined_at: string }[];
  related: { kind: Kind; slug: string }[];
  transfers: {
    id: number;
    from_user: string;
    to_user: string;
    by_user: string;
    kind: 'transfer' | 'reassign';
    reason: string;
    at: string;
  }[];
  proposal: ProposalView;
  impact: ImpactView;
  brief: Entry | null;
  thread: Entry[];
  positions: Position[];
  position_history: PositionHistory[];
  decision: DecisionRecord | null;
  has_new: boolean;
  can: {
    comment: boolean;
    edit_proposal: boolean;
    decide: boolean;
    transfer: boolean;
    joined: boolean;
  };
  mediator_error?: { code: string; message: string; problems?: string[] };
  issues?: string[];
}

export interface Notification {
  id: number;
  kind:
    | 'discussion_opened'
    | 'discussion_activity'
    | 'mention'
    | 'decider_nudge'
    | 'claim_expiring'
    | 'discussion_reassigned';
  subject_type: 'discussion' | 'work_item';
  subject_id: number;
  payload: Record<string, unknown>;
  created_at: string;
  read_at: string | null;
}

export interface DecisionSummary {
  discussion_id?: number;
  outcome: Outcome;
  rationale: string;
  decided_at: string;
  decider: string;
  version: number | null;
  status: 'validated' | 'proposed' | null;
}
