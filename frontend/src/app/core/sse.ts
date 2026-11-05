import { problemFrom } from './api';
import type { ApiProblem } from './models';

export interface SseEvent {
  event: string;
  data: unknown;
}

/** Splits an SSE byte stream into events. Pure, so it can be tested without a network. */
export class SseParser {
  private buffer = '';

  push(chunk: string): SseEvent[] {
    this.buffer += chunk.replace(/\r\n/g, '\n');
    const events: SseEvent[] = [];
    let end = this.buffer.indexOf('\n\n');
    while (end >= 0) {
      const block = this.buffer.slice(0, end);
      this.buffer = this.buffer.slice(end + 2);
      const parsed = parseBlock(block);
      if (parsed) {
        events.push(parsed);
      }
      end = this.buffer.indexOf('\n\n');
    }
    return events;
  }
}

function parseBlock(block: string): SseEvent | null {
  let event = 'message';
  const data: string[] = [];
  for (const line of block.split('\n')) {
    if (line.startsWith(':')) {
      continue; // comment / keep-alive
    }
    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      data.push(line.slice(5).replace(/^ /, ''));
    }
  }
  if (!data.length) {
    return null;
  }
  try {
    return { event, data: JSON.parse(data.join('\n')) };
  } catch {
    return null;
  }
}

/**
 * POSTs and reads a server-sent event stream with `fetch` (EventSource only does GET).
 * Resolves when the stream ends; rejects with an `ApiProblem` if the request itself fails.
 */
export async function postStream(
  path: string,
  body: unknown,
  csrf: string | null,
  onEvent: (event: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      method: 'POST',
      credentials: 'same-origin',
      signal,
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
      },
      body: JSON.stringify(body ?? {}),
    });
  } catch {
    throw problemFrom(0, null);
  }
  if (!response.ok || !response.body) {
    let parsed: unknown = null;
    try {
      parsed = await response.json();
    } catch {
      /* not JSON */
    }
    throw problemFrom(response.status, parsed) satisfies ApiProblem;
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    for (const event of parser.push(decoder.decode(value, { stream: true }))) {
      onEvent(event);
    }
  }
}
