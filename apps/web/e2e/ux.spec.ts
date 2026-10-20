import { expect, test } from '@playwright/test'

test('the window never scrolls sideways, even when it is small', async ({ page }) => {
  for (const width of [700, 880, 1280]) {
    await page.setViewportSize({ width, height: 800 })
    await page.goto('/')
    await expect(page.locator('.toolbar')).toBeVisible()
    for (const mode of ['Build', 'Explorer']) {
      await page.getByRole('tab', { name: mode }).click()
      const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(over, `${mode} at ${width}px`).toBeLessThanOrEqual(0)
    }
  }
})

test('the Explorer is mentioned on the first screen and has examples when empty', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Explore a GitHub repository' })).toBeVisible()
  await page.getByRole('button', { name: 'Explore a GitHub repository' }).click()
  await expect(page.getByText('See a codebase as nodes')).toBeVisible()
  await expect(page.getByRole('button', { name: /octocat\/Spoon-Knife/ })).toBeVisible()
})

test('new nodes have forms with explanations, and unconnected nodes are called out', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Add a Python node' }).click()
  await page.getByRole('button', { name: 'Add node' }).click()
  await page.getByRole('menuitem', { name: 'Filter list' }).click()
  await expect(page.getByLabel('Items path')).toBeVisible()
  await expect(page.getByLabel('Condition 1 operator')).toBeVisible()
  await expect(page.getByText(/Where the list is in the input/)).toBeVisible()
  await expect(page.getByRole('note')).toContainText('2 nodes aren’t connected to anything')
  await expect(page.getByText(/Idempotent/)).toHaveCount(0) // a pure data node has no retry settings
})

test.describe('with GitHub', () => {
  test.skip(!process.env.E2E_NETWORK, 'set E2E_NETWORK=1 to run against github.com')

  test('a real project opens readable: code first, root in view, no false alarms, easy to leave', async ({
    page,
  }) => {
    await page.goto('/')
    await page.getByRole('tab', { name: 'Explorer' }).click()
    await page.getByRole('button', { name: /pallets\/flask/ }).click()
    await expect(page.getByText(/Showing source code only/)).toBeVisible({ timeout: 60_000 })
    await expect(page.locator('.xn-file').first()).toBeVisible()
    expect(await page.locator('.xn').count()).toBeLessThanOrEqual(130)
    // the repository root is on screen at a readable zoom
    const root = page.locator('.xn-dir', { hasText: 'pallets/flask' })
    await expect(root).toBeInViewport({ timeout: 10_000 })
    const zoom = await page.evaluate(
      () => new DOMMatrix(getComputedStyle(document.querySelector('.react-flow__viewport')!).transform).a,
    )
    expect(zoom).toBeGreaterThanOrEqual(0.7)
    await expect(page.getByRole('tab', { name: /Problems/ })).not.toContainText('⚠')

    // switch the filter, then leave and come back through the list of imports
    await page.getByRole('button', { name: 'Code only' }).click()
    await expect(page.getByText(/Showing source code only/)).toHaveCount(0)
    await page.getByRole('button', { name: /All imports/ }).click()
    await expect(page.getByText('See a codebase as nodes')).toBeVisible()
    await expect(page.getByRole('region', { name: 'Recent imports' })).toContainText('pallets/flask')
    await page
      .getByRole('region', { name: 'Recent imports' })
      .getByRole('button', { name: /pallets\/flask/ })
      .first()
      .click()
    await expect(page.locator('.xn-file').first()).toBeVisible({ timeout: 30_000 })
  })
})
