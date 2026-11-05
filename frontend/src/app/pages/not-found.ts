import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

@Component({
  selector: 'app-not-found',
  changeDetection: ChangeDetectionStrategy.OnPush,
  imports: [RouterLink, TranslocoPipe],
  template: `
    <h1>{{ 'notfound.title' | transloco }}</h1>
    <p>{{ 'notfound.body' | transloco }}</p>
    <a routerLink="/consult" class="btn btn-secondary">{{ 'notfound.back' | transloco }}</a>
  `,
})
export class NotFoundPage {}
