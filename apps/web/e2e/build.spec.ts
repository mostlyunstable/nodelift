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

test('a webhook starts the workflow from outside the app, and a schedule can be added', async ({
  page,
  request,
}) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Workflows' }).click()
  await page.getByRole('menuitem', { name: /Example: Debug me/ }).click()
  await expect(page.locator('.code-node')).toHaveCount(4)
  await page.getByRole('button', { name: 'More actions' }).click()
  await page.getByRole('menuitem', { name: 'Triggers…' }).click()
  const dialog = page.getByRole('dialog', { name: 'Triggers' })

  await dialog.getByRole('button', { name: 'Add schedule' }).click()
  await expect(dialog.getByText('Every 15 minutes')).toBeVisible()

  await dialog.getByRole('button', { name: 'Create a webhook address' }).click()
  const address = (await dialog.locator('pre').first().textContent())!.trim()
  expect(address).toMatch(/\/hooks\/trg_[0-9a-f]+\/.{20,}/)
  // call it the way a script would: no app token, just the private address
  const res = await request.post(address, { data: { hello: 1 } })
  expect(res.status()).toBe(202)
  const runId = (await res.json()).run_id as string
  expect(runId).toBeTruthy()
  // the workflow really ran (the example is built to fail at one node)
  await expect
    .poll(
      async () => (await (await request.get(`http://127.0.0.1:8765/api/v1/runs/${runId}`)).json()).status,
      {
        timeout: 30_000,
      },
    )
    .toBe('failed')
  // a wrong token is refused
  expect((await request.post(address.replace(/\/[^/]+$/, '/wrong'))).status()).toBe(404)
})

test('the graph stays in view when the inspector opens', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Workflows' }).click()
  await page.getByRole('menuitem', { name: /Example: Debug me/ }).click()
  await expect(page.locator('.code-node')).toHaveCount(4)
  await page.locator('.code-node').nth(2).click() // opens the inspector and narrows the canvas
  await page.waitForTimeout(500)
  const canvas = (await page.locator('.canvas').boundingBox())!
  for (const n of await page.locator('.code-node').all()) {
    const b = (await n.boundingBox())!
    expect(b.x).toBeGreaterThanOrEqual(canvas.x - 1)
    expect(b.x + b.width).toBeLessThanOrEqual(canvas.x + canvas.width + 1)
  }
})
