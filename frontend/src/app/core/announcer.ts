import { Injectable, signal } from '@angular/core';

/**
 * Text for the polite live region in the shell (ui-spec 9: important asynchronous changes
 * are announced without moving focus).
 */
@Injectable({ providedIn: 'root' })
export class Announcer {
  readonly message = signal('');

  say(text: string): void {
    // clear first so repeating the same sentence is announced again
    this.message.set('');
    setTimeout(() => this.message.set(text), 50);
  }
}
