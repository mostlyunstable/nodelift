import AxeBuilder from '@axe-core/playwright'
import { githubCallsLeft } from './net'
import { expect, test, type Page } from '@playwright/test'

/** Fails with a readable list when a screen has accessibility violations (WCAG 2.1 A/AA and best practices). */
async function expectAccessible(page: Page, screen: string) {
  const r = await new AxeBuilder({ page })
    .exclude('.monaco-editor') // Monaco has its own accessibility support
    .exclude('iframe') // the sandboxed preview cannot be inspected
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'best-practice'])
    .analyze()
  const lines = r.violations.map(
    (v) =>
      `${v.id} [${v.impact}] ${v.help}: ${[...new Set(v.nodes.map((n) => n.target.join(' ')))].slice(0, 4).join(' | ')}`,
  )
  expect(lines, `accessibility problems on "${screen}"`).toEqual([])
}

for (const scheme of ['dark', 'light'] as const) {
  test.describe(`${scheme} theme`, () => {
    test.beforeEach(async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme })
      await page.goto('/')
      await page.evaluate((s) => document.documentElement.setAttribute('data-theme', s), scheme)
    })

    test('build screens have no violations', async ({ page }) => {
      await expectAccessible(page, 'build, empty')
      await page.getByRole('button', { name: 'Workflows' }).click()
      await expectAccessible(page, 'workflows menu')
      await page.getByRole('menuitem', { name: /Example: Debug me/ }).click()
      await page.locator('.code-node').first().waitFor()
      await expectAccessible(page, 'build, with nodes')
      await page.locator('.code-node').first().click()
      await expectAccessible(page, 'node selected (inspector, connections)')
      await page.getByRole('button', { name: /Run/ }).first().click()
      await page.locator('.code-node.status-failed').waitFor({ timeout: 30_000 })
      await expectAccessible(page, 'failed run')
      await page.keyboard.press('Control+k')
      await expectAccessible(page, 'command palette')
      await page.keyboard.press('Escape')
      await page.getByRole('button', { name: 'More actions' }).click()
      await page.getByRole('menuitem', { name: /Credentials/ }).click()
      await expectAccessible(page, 'credentials dialog')
      await page.keyboard.press('Escape')
      for (const name of ['Templates…', 'Files…', 'Triggers…']) {
        await page.getByRole('button', { name: 'More actions' }).click()
        await page.getByRole('menuitem', { name }).click()
        await expectAccessible(page, name)
        await page.keyboard.press('Escape')
      }
    })

    test('explorer welcome has no violations', async ({ page }) => {
      await page.getByRole('tab', { name: 'Explorer' }).click()
      await expectAccessible(page, 'explorer welcome')
    })

    test.describe('with GitHub', () => {
      test.skip(!process.env.E2E_NETWORK, 'set E2E_NETWORK=1 to run against github.com')
      test.beforeEach(async () => {
        test.skip(
          (await githubCallsLeft()) < 6,
          'GitHub allows 60 anonymous API calls an hour and they are used up; try later',
        )
      })
      test('explorer screens have no violations', async ({ page }) => {
        test.setTimeout(180_000)
        await page.getByRole('tab', { name: 'Explorer' }).click()
        await page.getByRole('button', { name: 'octocat/Spoon-Knife (3 files)' }).click()
        await page.locator('.xt-file').first().waitFor({ timeout: 60_000 })
        await page.waitForTimeout(1500)
        await expectAccessible(page, 'explorer graph')
        await page.locator('.xt-file', { hasText: 'index.html' }).locator('.xn-open').click()
        await page.waitForTimeout(1000)
        await expectAccessible(page, 'file source')
        await page.getByRole('tab', { name: /Details/ }).click()
        await expectAccessible(page, 'file details')
        await page.getByRole('tab', { name: 'Run' }).last().click()
        await expectAccessible(page, 'run tab')
        await page.getByRole('tab', { name: 'Problems' }).click()
        await expectAccessible(page, 'problems tab')
      })
    })
  })
}

test.describe('keyboard only', () => {
  test('the first Tab offers a skip link that moves focus into the workspace', async ({ page }) => {
    await page.goto('/')
    await page.keyboard.press('Tab')
    const skip = page.getByRole('link', { name: 'Skip to the workspace' })
    await expect(skip).toBeFocused()
    await expect(skip).toBeInViewport()
    await page.keyboard.press('Enter')
    await expect(page.locator('#main')).toBeFocused()
  })

  test('tabs use arrow keys, and only the selected tab is a tab stop', async ({ page }) => {
    await page.goto('/')
    const build = page.getByRole('tab', { name: 'Build' })
    await build.focus()
    await page.keyboard.press('ArrowRight')
    await expect(page.getByRole('tab', { name: 'Explorer' })).toBeFocused()
    await expect(page.getByRole('tab', { name: 'Explorer' })).toHaveAttribute('aria-selected', 'true')
    await expect(build).toHaveAttribute('tabindex', '-1')
    await page.keyboard.press('Home')
    await expect(build).toBeFocused()
  })

  test('two nodes can be connected and disconnected without a mouse', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: 'Add a Python node' }).click()
    await page.getByRole('button', { name: '+ Node (add a node)' }).click()
    await page.getByRole('menuitem', { name: 'Python code' }).click()
    await expect(page.locator('.code-node')).toHaveCount(2)
    await expect(page.getByRole('note')).toContainText('aren’t connected')
    await page.getByLabel('Send the output of this node to').selectOption({ index: 1 })
    await page.getByRole('button', { name: 'Connect' }).click()
    await expect(page.locator('.react-flow__edge')).toHaveCount(1)
    await expect(page.getByRole('note')).toHaveCount(0)
    await page.getByRole('button', { name: /Remove the connection to/ }).click()
    await expect(page.locator('.react-flow__edge')).toHaveCount(0)
  })

  test.describe('with GitHub', () => {
    test.skip(!process.env.E2E_NETWORK, 'set E2E_NETWORK=1 to run against github.com')
    test.beforeEach(async () => {
      test.skip(
        (await githubCallsLeft()) < 6,
        'GitHub allows 60 anonymous API calls an hour and they are used up; try later',
      )
    })

    test('the file list works with arrow keys, nodes open with Enter, and Back returns to the link box', async ({
      page,
    }) => {
      test.setTimeout(120_000)
      await page.goto('/')
      await page.getByRole('tab', { name: 'Explorer' }).click()
      await page.getByRole('button', { name: 'octocat/Spoon-Knife (3 files)' }).click()
      await page.locator('.xt-file').first().waitFor({ timeout: 60_000 })

      // file list: arrows move between items, Enter opens
      const tree = page.getByRole('tree', { name: 'Repository files' })
      await tree.getByRole('treeitem').first().focus()
      await page.keyboard.press('ArrowDown')
      await expect(tree.getByRole('treeitem').nth(1)).toBeFocused()
      await page.keyboard.press('End')
      await expect(tree.getByRole('treeitem').last()).toBeFocused()
      await page.keyboard.press('Enter')
      await expect(page.getByText(/read-only/)).toBeVisible()

      // graph node: focus it and press Enter
      await page.locator('.xt-file', { hasText: 'README.md' }).locator('.xn-open').focus()
      await page.keyboard.press('Enter')
      await expect(page.locator('.xt-file.selected', { hasText: 'README.md' })).toBeVisible()

      // back, with the link box ready for a different repository
      await page.getByRole('button', { name: '← All repositories' }).click()
      await expect(page.getByLabel('GitHub repository')).toBeFocused()
      await expect(page.getByText('See a codebase as nodes')).toBeVisible()
    })
  })
})
