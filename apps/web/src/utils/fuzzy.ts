/**
 * Subsequence match used by the command palette: every query character must appear in order.
 * Returns a score (higher is better) or null when it does not match. Prefers matches that start
 * words, are consecutive, and start early.
 */
export function fuzzyScore(query: string, text: string): number | null {
  const q = query.trim().toLowerCase()
  if (q === '') return 0
  const t = text.toLowerCase()
  let score = 0
  let ti = 0
  let streak = 0
  for (const ch of q) {
    if (ch === ' ') continue
    const found = t.indexOf(ch, ti)
    if (found === -1) return null
    const atWordStart = found === 0 || /[\s\-_/:.(]/.test(t[found - 1])
    streak = found === ti ? streak + 1 : 0
    score += 1 + (atWordStart ? 4 : 0) + streak * 2 - Math.min(found - ti, 6) * 0.2
    ti = found + 1
  }
  if (t.startsWith(q)) score += 10
  else if (t.includes(q)) score += 5 // the whole query appears as one piece
  return score - t.length * 0.02 // prefer shorter titles on ties
}

export function rank<T>(items: T[], query: string, text: (item: T) => string): T[] {
  return items
    .map((item, index) => ({ item, index, score: fuzzyScore(query, text(item)) }))
    .filter((r): r is { item: T; index: number; score: number } => r.score !== null)
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map((r) => r.item)
}
