import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Translation, TranslocoLoader } from '@jsverse/transloco';
import { Observable } from 'rxjs';

/** Loads `public/i18n/<lang>.json`. English is the default; others are just more files. */
@Injectable({ providedIn: 'root' })
export class TranslocoHttpLoader implements TranslocoLoader {
  private readonly http = inject(HttpClient);

  getTranslation(lang: string): Observable<Translation> {
    return this.http.get<Translation>(`/i18n/${lang}.json`);
  }
}

/** Picks `<key>.one` or `<key>.other` for a count, with the locale's plural rules. */
export function pluralKey(key: string, count: number, locale = 'en'): string {
  return `${key}.${new Intl.PluralRules(locale).select(count) === 'one' ? 'one' : 'other'}`;
}
