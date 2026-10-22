import { githubCallsLeft } from './net'
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
  await expect(page.getByRole('button', { name: 'octocat/Spoon-Knife (3 files)' })).toBeVisible()
})

test('new nodes have forms with explanations, and unconnected nodes are called out', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Add a Python node' }).click()
  await page.getByRole('button', { name: '+ Node (add a node)' }).click()
  await page.getByRole('menuitem', { name: 'Filter list' }).click()
  await expect(page.getByLabel('Items path')).toBeVisible()
  await expect(page.getByLabel('Condition 1 operator')).toBeVisible()
  await expect(page.getByText(/Where the list is in the input/)).toBeVisible()
  await expect(page.getByRole('note')).toContainText('2 nodes aren’t connected to anything')
  await expect(page.getByText(/Idempotent/)).toHaveCount(0) // a pure data node has no retry settings
})

test.describe('with GitHub', () => {
  test.skip(!process.env.E2E_NETWORK, 'set E2E_NETWORK=1 to run against github.com')
  test.beforeEach(async () => {
    test.skip(
      (await githubCallsLeft()) < 6,
      'GitHub allows 60 anonymous API calls an hour and they are used up; try later',
    )
  })

  test('a real project opens readable: code first, root in view, no false alarms, easy to leave', async ({
    page,
  }) => {
    await page.goto('/')
    await page.getByRole('tab', { name: 'Explorer' }).click()
    await page.getByRole('button', { name: /pallets\/flask/ }).click()
    await expect(page.getByText(/Showing source code only/)).toBeVisible({ timeout: 60_000 })
    await expect(page.locator('.xt-file').first()).toBeVisible()
    expect(await page.locator('.xt').count()).toBeLessThanOrEqual(130)
    // the repository is the hub in the middle, in view, and the whole network is framed rather than cut off
    const root = page.locator('.xt-folder.root')
    await expect(root).toBeInViewport({ timeout: 10_000 })
    const zoom = await page.evaluate(
      () => new DOMMatrix(getComputedStyle(document.querySelector('.react-flow__viewport')!).transform).a,
    )
    expect(zoom).toBeGreaterThanOrEqual(0.2)
    await expect(page.getByRole('tab', { name: /Problems/ })).not.toContainText('⚠')

    // switch the filter, then leave and come back through the list of imports
    await page.getByRole('button', { name: 'Code only' }).click()
    await expect(page.getByText(/Showing source code only/)).toHaveCount(0)
    await page.getByRole('button', { name: '← All repositories' }).click()
    await expect(page.getByText('See a codebase as nodes')).toBeVisible()
    await expect(page.getByRole('region', { name: 'Recent imports' })).toContainText('pallets/flask')
    await page
      .getByRole('region', { name: 'Recent imports' })
      .getByRole('button', { name: /pallets\/flask/ })
      .first()
      .click()
    await expect(page.locator('.xt-file').first()).toBeVisible({ timeout: 30_000 })
  })
})

test('the code editor keeps its height when the window is short', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 520 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Add a Python node' }).click()
  await page.getByRole('button', { name: '+ Node (add a node)' }).click()
  await page.getByRole('menuitem', { name: 'Python code' }).click()
  await page.locator('.code-node').first().click()
  await expect(page.locator('.editor .monaco-editor')).toBeVisible({ timeout: 30_000 })
  const h = await page.locator('.editor').evaluate((el) => el.getBoundingClientRect().height)
  expect(h).toBeGreaterThanOrEqual(200)
  // the settings panel scrolls instead
  const scrolls = await page.locator('.inspector').evaluate((el) => el.scrollHeight > el.clientHeight)
  expect(scrolls).toBe(true)
})

test('menus open fully over the page and never scroll or clip the toolbar', async ({ page }) => {
  for (const size of [
    { width: 1280, height: 800 },
    { width: 900, height: 600 },
  ]) {
    await page.setViewportSize(size)
    await page.goto('/')
    for (const name of ['Workflows', 'More actions', '+ Node']) {
      await page.getByRole('button', { name }).click()
      const menu = page.getByRole('menu')
      await expect(menu).toBeVisible()
      const box = (await menu.boundingBox())!
      expect(box.y, `${name} starts below the toolbar`).toBeGreaterThanOrEqual(30)
      expect(box.x).toBeGreaterThanOrEqual(0)
      expect(box.x + box.width).toBeLessThanOrEqual(size.width)
      expect(box.y + box.height).toBeLessThanOrEqual(size.height)
      // every item is on screen, so none is cut off by the toolbar
      for (const item of await menu.getByRole('menuitem').all()) await expect(item).toBeInViewport()
      expect(await page.locator('.toolbar').evaluate((el) => el.scrollTop)).toBe(0)
      expect(await page.evaluate(() => document.scrollingElement!.scrollTop)).toBe(0)
      await page.keyboard.press('Escape')
      await expect(menu).toHaveCount(0)
    }
  }
})
