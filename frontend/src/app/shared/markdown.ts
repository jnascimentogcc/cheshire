import DOMPurify from 'dompurify';
import { marked } from 'marked';

const ALLOWED_TAGS = ['em', 'strong', 'code', 'a', 'br'];

/**
 * Inline Markdown to safe HTML (ui-spec 12): the text is parsed, then sanitised with a
 * short allow-list before it reaches the DOM. Links get `rel="noopener noreferrer"`.
 */
export function renderInline(text: string): string {
  const html = marked.parseInline(text, { async: false });
  const clean = DOMPurify.sanitize(html, { ALLOWED_TAGS, ALLOWED_ATTR: ['href', 'target', 'rel'] });
  return clean.replace(/<a /g, '<a rel="noopener noreferrer" target="_blank" ');
}
