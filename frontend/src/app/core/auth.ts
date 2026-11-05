import { HttpErrorResponse } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { firstValueFrom } from 'rxjs';

import { Api, CsrfToken } from './api';
import type { Role, SessionInfo, User } from './models';
import { UserPreferences } from './preferences';

const RANK: Record<Role, number> = { user: 0, architect: 1, admin: 2 };

@Injectable({ providedIn: 'root' })
export class Auth {
  private readonly api = inject(Api);
  private readonly csrf = inject(CsrfToken);
  private readonly prefs = inject(UserPreferences);

  readonly user = signal<User | null>(null);
  readonly ready = signal(false);
  readonly isArchitect = computed(() => this.atLeast('architect'));

  atLeast(role: Role): boolean {
    const user = this.user();
    return !!user && RANK[user.role] >= RANK[role];
  }

  /** Restores the session from the cookie, once, at start-up. */
  async restore(): Promise<void> {
    if (this.ready()) {
      return;
    }
    try {
      await this.adopt(await firstValueFrom(this.api.get<SessionInfo>('/auth/me')));
    } catch (error) {
      if (!(error instanceof HttpErrorResponse) || error.status !== 401) {
        // the API is unreachable: stay signed out, the login page explains
        this.user.set(null);
      }
    } finally {
      this.ready.set(true);
    }
  }

  async login(email: string, password: string): Promise<void> {
    const session = await firstValueFrom(
      this.api.post<SessionInfo>('/auth/login', { email, password }),
    );
    await this.adopt(session);
  }

  async logout(): Promise<void> {
    try {
      await firstValueFrom(this.api.post<unknown>('/auth/logout'));
    } finally {
      this.user.set(null);
      this.csrf.value.set(null);
    }
  }

  private async adopt(session: SessionInfo): Promise<void> {
    this.csrf.value.set(session.csrf_token);
    this.user.set(session.user);
    await this.prefs.load();
  }
}

export const requireLogin: CanActivateFn = async (_route, state) => {
  const auth = inject(Auth);
  const router = inject(Router); // inject() only works before the first await
  await auth.restore();
  if (auth.user()) {
    return true;
  }
  return router.createUrlTree(['/login'], { queryParams: { next: state.url } });
};

/** Architect-only screens (editing, queue tools). Others are sent to the read-only catalog. */
export const requireArchitect: CanActivateFn = async () => {
  const auth = inject(Auth);
  const router = inject(Router);
  await auth.restore();
  return auth.isArchitect() ? true : router.createUrlTree(['/catalog']);
};
