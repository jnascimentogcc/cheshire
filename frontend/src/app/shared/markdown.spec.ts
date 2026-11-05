import { renderInline } from './markdown';

describe('renderInline', () => {
  it('keeps simple emphasis', () => {
    expect(renderInline('a **bold** and `code`')).toBe(
      'a <strong>bold</strong> and <code>code</code>',
    );
  });

  it('removes scripts, handlers and images', () => {
    const html = renderInline('x <script>alert(1)</script><img src=x onerror=alert(1)> y');
    expect(html).not.toContain('script');
    expect(html).not.toContain('onerror');
    expect(html).not.toContain('<img');
  });

  it('opens links safely', () => {
    const html = renderInline('[docs](https://example.org)');
    expect(html).toContain('rel="noopener noreferrer"');
    expect(html).toContain('href="https://example.org"');
  });

  it('drops javascript: links', () => {
    expect(renderInline('[x](javascript:alert(1))')).not.toContain('javascript:');
  });
});
