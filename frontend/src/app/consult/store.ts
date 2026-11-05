import { HttpClient } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { TranslocoService } from '@jsverse/transloco';
import { Observable, firstValueFrom } from 'rxjs';

import { Announcer } from '../core/announcer';
import { Api, CsrfToken, toProblem } from '../core/api';
import { pluralKey } from '../core/i18n';
import type { ApiProblem, Consultation, DetailLevel, StageName } from '../core/models';
import { UserPreferences } from '../core/preferences';
import { SseEvent, postStream } from '../core/sse';
import { summarize } from './logic';

/** Where a failure is shown: next to the region it affects (ui-spec 7). */
export type Region =
  'analysis' | 'understood' | 'questions' | 'rationale' | 'choices' | 'feedback' | 'export' | 'pin';

/**
 * State of the session page. It lives at the root so the stream that starts on
 * `/consult/new` keeps running while the router moves to `/consult/:id`.
 */
@Injectable({ providedIn: 'root' })
export class SessionStore {
  private readonly api = inject(Api);
  private readonly http = inject(HttpClient);
  private readonly csrf = inject(CsrfToken);
  private readonly announcer = inject(Announcer);
  private readonly i18n = inject(TranslocoService);
  private readonly prefs = inject(UserPreferences);

  readonly consultation = signal<Consultation | null>(null);
  readonly loading = signal(false);
  readonly loadProblem = signal<ApiProblem | null>(null);
  /** Stage of the running analysis; null once the result is in (or nothing is running). */
  readonly stage = signal<StageName | null>(null);
  readonly problems = signal<Partial<Record<Region, ApiProblem>>>({});
  readonly busy = signal<Partial<Record<Region, boolean>>>({});

  private currentId: number | null = null;
  private currentRevision: number | null = null;
  private pendingCreated: ((id: number) => void) | null = null;

  // ---------------------------------------------------------------- loading

  /** Opens a consultation. A stream that is already filling it is left alone. */
  async open(id: number, revision: number | null = null): Promise<void> {
    if (
      this.currentId === id &&
      this.currentRevision === revision &&
      (this.stage() || this.consultation())
    ) {
      return;
    }
    this.reset(id);
    this.currentRevision = revision;
    await this.refresh();
  }

  async refresh(): Promise<void> {
    const id = this.currentId;
    if (id === null) {
      return;
    }
    this.loading.set(true);
    this.loadProblem.set(null);
    try {
      const query = this.currentRevision ? `?revision=${this.currentRevision}` : '';
      const view = await firstValueFrom(this.api.get<Consultation>(`/consultations/${id}${query}`));
      if (this.currentId === id) {
        this.consultation.set(view);
      }
    } catch (error) {
      if (this.currentId === id) {
        this.loadProblem.set(toProblem(error));
      }
    } finally {
      this.loading.set(false);
    }
  }

  private reset(id: number | null): void {
    this.currentId = id;
    this.currentRevision = null;
    this.consultation.set(null);
    this.loadProblem.set(null);
    this.stage.set(null);
    this.problems.set({});
    this.busy.set({});
  }

  // --------------------------------------------------------------- analysis

  /** Creates a consultation and analyzes it; `onCreated` fires as soon as it has an id. */
  async startNew(
    requirement: string,
    title: string,
    onCreated: (id: number) => void,
  ): Promise<void> {
    this.reset(null);
    this.pendingCreated = onCreated;
    await this.stream('/consultations/stream', { requirement, title });
  }

  async revise(requirement: string): Promise<void> {
    if (this.currentId === null) {
      return;
    }
    await this.stream(`/consultations/${this.currentId}/revisions/stream`, { requirement });
  }

  async retryAnalysis(): Promise<void> {
    if (this.currentId === null) {
      return;
    }
    await this.stream(`/consultations/${this.currentId}/analyze/stream`, {});
  }

  private async stream(path: string, body: unknown): Promise<void> {
    this.setProblem('analysis', null);
    this.stage.set('interpreting');
    let failed = false;
    try {
      await postStream(path, body, this.csrf.value(), (event) => {
        failed = this.onEvent(event) || failed;
      });
    } catch (error) {
      failed = true;
      this.setProblem('analysis', toProblem(error));
    } finally {
      this.stage.set(null);
      this.setBusy('rationale', false);
      this.pendingCreated = null;
    }
    if (failed && this.currentId !== null) {
      await this.refresh(); // the text was kept: show it with "Try again"
    }
  }

  /** Returns true when the event reports a failure of the analysis. */
  private onEvent(event: SseEvent): boolean {
    const data = event.data as Record<string, unknown>;
    switch (event.event) {
      case 'created': {
        const id = Number(data['id']);
        this.currentId = id;
        this.pendingCreated?.(id);
        return false;
      }
      case 'stage': {
        const stage = data['stage'] as StageName;
        if (stage === 'writing') {
          this.setBusy('rationale', true);
        } else {
          this.stage.set(stage);
        }
        return false;
      }
      case 'result':
        this.stage.set(null);
        this.apply(data as unknown as Consultation);
        return false;
      case 'rationale':
        this.setBusy('rationale', false);
        this.consultation.set(data as unknown as Consultation);
        return false;
      case 'rationale_error':
        this.setBusy('rationale', false);
        this.setProblem('rationale', toApiProblem(data));
        return false;
      case 'error':
        this.setProblem('analysis', toApiProblem(data));
        return true;
      default:
        return false;
    }
  }

  // ---------------------------------------------------------------- changes

  answer(attribute: string, value: string | string[]): Promise<void> {
    return this.act('questions', () =>
      this.api.post<Consultation>(`/consultations/${this.currentId}/answers`, { attribute, value }),
    );
  }

  editFact(attribute: string, value: string | string[]): Promise<void> {
    return this.act('understood', () =>
      this.api.put<Consultation>(`/consultations/${this.currentId}/facts/${attribute}`, { value }),
    );
  }

  addAbb(abb: string): Promise<void> {
    return this.act('understood', () =>
      this.api.post<Consultation>(`/consultations/${this.currentId}/abbs`, { abb }),
    );
  }

  removeAbb(abb: string): Promise<void> {
    return this.act('understood', () =>
      this.api.delete<Consultation>(`/consultations/${this.currentId}/abbs/${abb}`),
    );
  }

  generateRationale(detail: DetailLevel = this.prefs.detail()): Promise<void> {
    return this.act('rationale', () =>
      this.api.post<Consultation>(`/consultations/${this.currentId}/rationale`, { detail }),
    );
  }

  choose(abb: string, kind: string, sbb: string | null, reason: string): Promise<void> {
    return this.act('choices', () =>
      this.api.post<Consultation>(`/consultations/${this.currentId}/choices`, {
        abb,
        kind,
        sbb,
        reason,
      }),
    );
  }

  sendFeedback(kind: 'missing' | 'wrong', text: string, abb: string | null): Promise<void> {
    return this.act('feedback', () =>
      this.api.post<Consultation>(`/consultations/${this.currentId}/feedback`, { kind, text, abb }),
    );
  }

  pin(title: string): Promise<void> {
    return this.act('pin', () =>
      this.api.put<Consultation>(`/consultations/${this.currentId}/pin`, { title }),
    );
  }

  unpin(): Promise<void> {
    return this.act('pin', () =>
      this.api.delete<Consultation>(`/consultations/${this.currentId}/pin`),
    );
  }

  /** Downloads the export; the file name comes from the server. */
  async download(format: 'markdown' | 'json'): Promise<void> {
    if (this.currentId === null) {
      return;
    }
    const id = this.currentId;
    this.setBusy('export', true);
    this.setProblem('export', null);
    try {
      const response = await firstValueFrom(
        this.http.get(`/api/consultations/${id}/export`, {
          params: { format },
          responseType: 'blob',
          observe: 'response',
        }),
      );
      const url = URL.createObjectURL(response.body as Blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `consultation-${id}.${format === 'json' ? 'json' : 'md'}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      this.setProblem('export', toProblem(error));
    } finally {
      this.setBusy('export', false);
    }
  }

  private async act(region: Region, call: () => Observable<Consultation>): Promise<void> {
    if (this.currentId === null) {
      return;
    }
    const id = this.currentId;
    this.setBusy(region, true);
    this.setProblem(region, null);
    try {
      const view = await firstValueFrom(call());
      if (this.currentId === id) {
        this.apply(view);
      }
    } catch (error) {
      this.setProblem(region, toProblem(error));
    } finally {
      this.setBusy(region, false);
    }
  }

  /** Shows a new view and announces what changed, politely (consult.md 7). */
  private apply(view: Consultation): void {
    const previous = this.consultation();
    this.consultation.set(view);
    if (!view.evaluation) {
      return;
    }
    const changed = previous?.evaluation?.id !== view.evaluation.id;
    if (previous && changed) {
      const s = summarize(view.evaluation.result);
      const locale = this.prefs.locale();
      this.announcer.say(
        `${this.i18n.translate(pluralKey('live.questions', s.questions, locale), { n: s.questions })}, ` +
          this.i18n.translate(pluralKey('live.gaps', s.gaps, locale), { n: s.gaps }),
      );
    }
  }

  private setProblem(region: Region, problem: ApiProblem | null): void {
    this.problems.update((all) => {
      const next = { ...all };
      if (problem) {
        next[region] = problem;
      } else {
        delete next[region];
      }
      return next;
    });
  }

  private setBusy(region: Region, value: boolean): void {
    this.busy.update((all) => ({ ...all, [region]: value }));
  }
}

function toApiProblem(data: Record<string, unknown>): ApiProblem {
  return {
    status: 0,
    code: String(data['code'] ?? 'internal'),
    message: String(data['message'] ?? ''),
    problems: Array.isArray(data['problems']) ? (data['problems'] as string[]) : undefined,
  };
}
