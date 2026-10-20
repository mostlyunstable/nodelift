import { expect, test } from '@playwright/test'

test('the Debug me example runs for real and shows what each node did', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Workflows' }).click()
  await page.getByRole('menuitem', { name: /Example: Debug me/ }).click()
  await expect(page.locator('.code-node')).toHaveCount(4)

  await page.getByRole('button', { name: /Run/ }).first().click()
  // statuses come from the backend, never from the page guessing
  await expect(page.locator('.code-node.status-failed')).toHaveCount(1, { timeout: 30_000 })
  await expect(page.locator('.code-node.status-succeeded')).toHaveCount(2)
  await expect(page.locator('.code-node.status-skipped')).toHaveCount(1)
  await expect(page.locator('.code-node.status-failed')).toContainText('Average')
})

test('your work survives a reload', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Workflows' }).click()
  await page.getByRole('menuitem', { name: /Example: Debug me/ }).click()
  await expect(page.locator('.code-node')).toHaveCount(4)
  await expect(page.getByRole('status', { name: 'Save status' })).toHaveText('Saved', { timeout: 15_000 })
  await page.reload()
  await expect(page.locator('.code-node')).toHaveCount(4)
})

test('a code node cannot reach the network or your home folder (confined on macOS)', async ({
  page,
  browserName,
}) => {
  test.skip(process.platform !== 'darwin', 'confinement is macOS-only')
  await page.goto('/')
  const res = await page.request.post('/api/v1/nodes/code/test', {
    data: {
      source:
        'import os, socket\n' +
        'def main(i):\n' +
        '    try:\n        socket.create_connection(("1.1.1.1", 53), timeout=2); net = "allowed"\n    except Exception as e:\n        net = "denied"\n' +
        '    try:\n        os.listdir(os.path.expanduser("~")); home = "allowed"\n    except Exception:\n        home = "denied"\n' +
        '    return {"net": net, "home": home}\n',
      input: {},
    },
  })
  const body = await res.json()
  expect(body.output).toEqual({ net: 'denied', home: 'denied' })
  expect(browserName).toBeTruthy()
})
