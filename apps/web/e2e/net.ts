/** Anonymous GitHub allows 60 API calls an hour and every import spends two. Say so instead of failing mysteriously. */
export async function githubCallsLeft(): Promise<number> {
  try {
    const r = await fetch('https://api.github.com/rate_limit', { headers: { 'User-Agent': 'nodecraft-e2e' } })
    const j = (await r.json()) as { resources: { core: { remaining: number } } }
    return j.resources.core.remaining
  } catch {
    return 0
  }
}
