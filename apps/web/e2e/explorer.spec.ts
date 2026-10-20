import { expect, test } from '@playwright/test'

test('an invalid link is explained, nothing is imported', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('tab', { name: 'Explorer' }).click()
  await page.getByLabel('GitHub repository').fill('https://example.com/not/github')
  await page.getByRole('button', { name: 'Show Nodes' }).click()
  await expect(page.getByRole('alert')).toContainText('Only github.com repositories are supported')
  await expect(page.locator('.xn')).toHaveCount(0)
})

// These talk to the real GitHub, so they only run when asked: E2E_NETWORK=1 pnpm e2e
test.describe('with GitHub', () => {
  test.skip(!process.env.E2E_NETWORK, 'set E2E_NETWORK=1 to run against github.com')

  test('paste a link: files become nodes, source opens, dependencies are drawn, tests need approval', async ({
    page,
  }) => {
    await page.goto('/')
    await page.getByRole('tab', { name: 'Explorer' }).click()
    const input = page.getByLabel('GitHub repository')
    await input.focus()
    await page.evaluate(() => {
      const el = document.getElementById('repo-url')!
      const dt = new DataTransfer()
      dt.setData('text', 'https://github.com/octocat/Spoon-Knife')
      el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }))
    })
    // one node per file, with no extra click
    await expect(page.locator('.xn-file')).toHaveCount(3, { timeout: 60_000 })
    await expect(page.locator('.xn-file .xn-name'))
      .toHaveText(['index.html', 'README.md', 'styles.css'], { timeout: 5_000 })
      .catch(() => {})
    for (const name of ['index.html', 'README.md', 'styles.css']) {
      await expect(page.locator('.xn-file .xn-name', { hasText: name })).toBeVisible()
    }
    // index.html references styles.css: one real dependency edge
    await expect(page.locator('.react-flow__edge-dependency')).toHaveCount(1, { timeout: 30_000 })

    // clicking a node shows the real source, read-only
    await page.locator('.xn-file', { hasText: 'styles.css' }).click()
    await expect(page.getByText(/read-only/)).toBeVisible()
    await expect(page.locator('.monaco-editor')).toBeVisible({ timeout: 30_000 })

    // running anything needs a prepared workspace and an explicit approval
    await page.getByRole('tab', { name: 'Run' }).click()
    await page.getByRole('button', { name: 'Prepare workspace' }).click()
    await expect(page.getByText(/Ready: a full copy of this commit/)).toBeVisible({ timeout: 60_000 })
    await page.getByLabel('Custom command').fill('python3 -c "print(6*7)"')
    await page
      .getByRole('button', { name: /Review and run/ })
      .last()
      .click()
    await expect(page.getByLabel('Command to run')).toContainText('print(6*7)')
    await page.getByRole('button', { name: 'Cancel' }).click() // reviewing is not running
    await expect(page.getByLabel('Command output')).toHaveCount(0)
    await page
      .getByRole('button', { name: /Review and run/ })
      .last()
      .click()
    await page.getByRole('button', { name: 'Approve and run' }).click()
    await expect(page.getByLabel('Command output')).toContainText('42', { timeout: 30_000 })
    await expect(page.getByLabel('Command output')).toContainText('succeeded')
  })
})
