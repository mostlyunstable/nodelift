import type { ThemeChoice } from './store'

/** The theme actually in effect: "system" follows the operating system. */
export function resolveTheme(choice: ThemeChoice): 'dark' | 'light' {
  if (choice !== 'system') return choice
  return (typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches) ===
    false
    ? 'light'
    : 'dark'
}
