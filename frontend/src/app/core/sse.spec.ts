import { problemFrom } from './api';
import { SseParser } from './sse';

describe('SseParser', () => {
  it('reads events split across chunks', () => {
    const parser = new SseParser();
    expect(parser.push('event: stage\ndata: {"stage":"inter')).toEqual([]);
    expect(parser.push('preting"}\n\nevent: done\ndata: {}\n\n')).toEqual([
      { event: 'stage', data: { stage: 'interpreting' } },
      { event: 'done', data: {} },
    ]);
  });

  it('handles CRLF, comments and unnamed events', () => {
    const parser = new SseParser();
    expect(parser.push(': keep-alive\r\n\r\ndata: {"a":1}\r\n\r\n')).toEqual([
      { event: 'message', data: { a: 1 } },
    ]);
  });

  it('skips blocks that are not valid JSON', () => {
    const parser = new SseParser();
    expect(parser.push('event: x\ndata: not json\n\nevent: y\ndata: 2\n\n')).toEqual([
      { event: 'y', data: 2 },
    ]);
  });
});

describe('problemFrom', () => {
  it('reads the {code, message} detail the API returns', () => {
    expect(
      problemFrom(502, {
        detail: { code: 'llm_output_rejected', message: 'm', problems: ['p'] },
      }),
    ).toEqual({
      status: 502,
      code: 'llm_output_rejected',
      message: 'm',
      problems: ['p'],
      detail: { code: 'llm_output_rejected', message: 'm', problems: ['p'] },
    });
  });

  it('falls back to the status for plain errors', () => {
    expect(problemFrom(401, { detail: 'authentication required' })).toEqual({
      status: 401,
      code: 'http_401',
      message: 'authentication required',
    });
    expect(problemFrom(429, {}).code).toBe('rate_limited');
    expect(problemFrom(0, null).code).toBe('network');
  });

  it('does not leak validation internals', () => {
    expect(problemFrom(422, { detail: [{ loc: ['body'], msg: 'x' }] })).toEqual({
      status: 422,
      code: 'invalid_input',
      message: '',
      problems: undefined,
    });
  });
});
