import { HttpClient, HttpErrorResponse, HttpInterceptorFn } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, catchError, throwError } from 'rxjs';

import type { ApiProblem } from './models';

/** Holds the CSRF token of the current session (docs/api.md, Authentication). */
@Injectable({ providedIn: 'root' })
export class CsrfToken {
  readonly value = signal<string | null>(null);
}

/** Every non-GET request carries the CSRF header; 401 sends the user to the login. */
export const apiInterceptor: HttpInterceptorFn = (req, next) => {
  const csrf = inject(CsrfToken).value();
  const router = inject(Router);
  const outgoing =
    req.method !== 'GET' && csrf ? req.clone({ setHeaders: { 'X-CSRF-Token': csrf } }) : req;
  return next(outgoing).pipe(
    catchError((error: unknown) => {
      if (
        error instanceof HttpErrorResponse &&
        error.status === 401 &&
        !req.url.endsWith('/api/auth/login') &&
        !req.url.endsWith('/api/auth/me')
      ) {
        void router.navigate(['/login']);
      }
      return throwError(() => error);
    }),
  );
};

/** Turns any HTTP failure into the `{code, message}` shape the UI shows. */
export function toProblem(error: unknown): ApiProblem {
  if (error instanceof HttpErrorResponse) {
    return problemFrom(error.status, error.error);
  }
  if (isProblem(error)) {
    return error;
  }
  return { status: 0, code: 'network', message: '' };
}

export function problemFrom(status: number, body: unknown): ApiProblem {
  const detail =
    body && typeof body === 'object' && 'detail' in body
      ? (body as { detail: unknown }).detail
      : body;
  if (detail && typeof detail === 'object' && 'code' in detail) {
    const d = detail as { code: string; message?: string; problems?: string[] };
    return {
      status,
      code: d.code,
      message: d.message ?? '',
      problems: d.problems,
      detail: detail as Record<string, unknown>,
    };
  }
  if (Array.isArray(detail)) {
    return { status, code: 'invalid_input', message: '' };
  }
  const code = status === 0 ? 'network' : status === 429 ? 'rate_limited' : `http_${status}`;
  return { status, code, message: typeof detail === 'string' ? detail : '' };
}

function isProblem(value: unknown): value is ApiProblem {
  return !!value && typeof value === 'object' && 'code' in value && 'status' in value;
}

/** Thin wrapper so pages never build URLs or headers themselves. */
@Injectable({ providedIn: 'root' })
export class Api {
  private readonly http = inject(HttpClient);

  get<T>(path: string): Observable<T> {
    return this.http.get<T>(`/api${path}`);
  }

  post<T>(path: string, body: unknown = {}): Observable<T> {
    return this.http.post<T>(`/api${path}`, body);
  }

  put<T>(path: string, body: unknown = {}): Observable<T> {
    return this.http.put<T>(`/api${path}`, body);
  }

  patch<T>(path: string, body: unknown = {}): Observable<T> {
    return this.http.patch<T>(`/api${path}`, body);
  }

  delete<T>(path: string): Observable<T> {
    return this.http.delete<T>(`/api${path}`);
  }
}
