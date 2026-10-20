/**
 * A document for the sandboxed preview iframe. The iframe has `sandbox=""` (no scripts, no same-origin,
 * no forms, no navigation) and this CSP forbids every network fetch, so repository HTML can neither run
 * code nor reach Nodecraft's origin or the network. Only inline styles and `data:` images render.
 */
export const PREVIEW_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:"

export function buildPreviewDoc(html: string): string {
  return `<meta http-equiv="Content-Security-Policy" content="${PREVIEW_CSP}">${html}`
}
