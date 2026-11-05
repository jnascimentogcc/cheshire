import { DOCUMENT } from '@angular/common';
import { Injectable, inject, signal } from '@angular/core';
import { firstValueFrom } from 'rxjs';

import { Api } from './api';
import type { DetailLevel, Preferences, ThemePreference } from './models';

const THEME_KEY = 'cheshire.theme';

/**
 * Detail level, theme and locale, stored on the server so they follow the user
 * (consult.md 4, ui-spec 11). The theme is also kept in localStorage so the first paint
 * uses it before the server answers (see public/theme-init.js).
 */
@Injectable({ providedIn: 'root' })
export class UserPreferences {
  private readonly api = inject(Api);
  private readonly document = inject(DOCUMENT);

  readonly detail = signal<DetailLevel>('summary');
  readonly theme = signal<ThemePreference>(this.savedTheme());
  readonly locale = signal('en');

  constructor() {
    this.applyTheme(this.theme());
    const media = this.document.defaultView?.matchMedia?.('(prefers-color-scheme: dark)');
    media?.addEventListener?.('change', () => this.applyTheme(this.theme()));
  }

  async load(): Promise<void> {
    try {
      this.adopt(await firstValueFrom(this.api.get<Preferences>('/preferences')));
    } catch {
      /* defaults are fine; the page works without saved preferences */
    }
  }

  async setDetail(detail: DetailLevel): Promise<void> {
    this.detail.set(detail);
    await this.save({ detail_level: detail });
  }

  async setTheme(theme: ThemePreference): Promise<void> {
    this.theme.set(theme);
    this.applyTheme(theme);
    await this.save({ theme });
  }

  private async save(change: Partial<Preferences>): Promise<void> {
    try {
      await firstValueFrom(this.api.put<Preferences>('/preferences', change));
    } catch {
      /* the choice still applies in this session */
    }
  }

  private adopt(prefs: Preferences): void {
    this.detail.set(prefs.detail_level);
    this.locale.set(prefs.locale);
    this.theme.set(prefs.theme);
    this.applyTheme(prefs.theme);
  }

  private applyTheme(theme: ThemePreference): void {
    const prefersDark = !!this.document.defaultView?.matchMedia?.('(prefers-color-scheme: dark)')
      .matches;
    const dark = theme === 'dark' || (theme === 'system' && prefersDark);
    this.document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* storage can be blocked */
    }
  }

  private savedTheme(): ThemePreference {
    try {
      const saved = localStorage.getItem(THEME_KEY);
      return saved === 'light' || saved === 'dark' ? saved : 'system';
    } catch {
      return 'system';
    }
  }
}
