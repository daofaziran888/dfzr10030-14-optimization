import { expect, test, type Page } from '@playwright/test'

/**
 * 重复影响摘要：按窗口汇总重复记录，不展开全部原始记录逐条比对。
 * 覆盖两个成立边界（窗口整段 / 版本新增）、同窗唯一版本、并发只留一份、
 * 历史版本核对、血缘接力与去重回查。
 */
test.describe.configure({ mode: 'serial' })

async function openImpact(page: Page) {
  await page.goto('/dedup')
  await page.getByTestId('open-impact').click()
  await expect(page.getByTestId('impact-panel')).toBeVisible()
}

test('去重页：按窗口汇总重复影响，展开可见被替换记录范围', async ({ page }) => {
  const browserErrors: string[] = []
  page.on('pageerror', (e) => browserErrors.push(e.message))
  page.on('response', (r) => {
    if (r.url().includes('/api/') && r.status() >= 400) browserErrors.push(`${r.status()} ${r.url()}`)
  })
  await openImpact(page)

  await page.getByTestId('impact-window').selectOption('2026-09-01')
  await page.getByTestId('impact-scope').selectOption('window')
  await page.getByTestId('impact-preview').click()
  await expect(page.getByTestId('impact-preview-card')).toBeVisible()
  await expect(page.getByTestId('preview-duplicate')).toHaveText('14')
  await expect(page.getByTestId('preview-replaced')).toHaveText('9')

  await page.getByTestId('impact-generate').click()
  await expect(page.getByTestId('impact-message')).toContainText('已生成')
  const row = page.locator('[data-testid^="impact-row-"]').filter({ hasText: '2026-09-01' }).first()
  await expect(row.getByTestId('summary-duplicate')).toHaveText('14')
  await expect(row.getByTestId('summary-replaced')).toHaveText('9')
  await expect(row.getByTestId('summary-version')).toHaveText('v2')

  const summaryId = (await row.getAttribute('data-testid'))!.replace('impact-row-', '')
  if (!(await page.getByTestId(`impact-detail-${summaryId}`).isVisible())) {
    await page.getByTestId(`impact-expand-${summaryId}`).click()
  }
  await expect(page.getByTestId(`impact-detail-${summaryId}`)).toBeVisible()
  await expect(page.getByTestId('impact-group-2026-09-01-G01')).toBeVisible()
  await expect(page.getByTestId(`impact-detail-${summaryId}`)).toContainText('被替换')

  // 同一窗口同口径重复生成必须被拒绝
  await page.getByTestId('impact-generate').click()
  await expect(page.getByTestId('impact-message')).toContainText('同一窗口只保留一份结果')
  await expect(page.locator('[data-testid^="impact-row-"]').filter({ hasText: '2026-09-01' })).toHaveCount(1)

  expect(browserErrors).toEqual([])
})

test('去重页：版本口径只展示新增影响，与窗口口径结果不同', async ({ page }) => {
  await openImpact(page)
  await page.getByTestId('impact-window').selectOption('2026-09-01')
  await page.getByTestId('impact-scope').selectOption('version')
  await page.getByTestId('impact-preview').click()
  await expect(page.getByTestId('preview-duplicate')).toHaveText('7')
  await expect(page.getByTestId('preview-replaced')).toHaveText('5')
})

test('去重页：历史版本核对不一致时按历史版本判定并保留原记录', async ({ page }) => {
  await openImpact(page)
  await page.getByTestId('impact-window').selectOption('2026-09-02')
  await page.getByTestId('impact-scope').selectOption('window')
  await page.getByTestId('impact-generate').click()
  await expect(page.getByTestId('impact-message')).toContainText('已生成')
  const row = page.locator('[data-testid^="impact-row-"]').filter({ hasText: '2026-09-02' }).first()
  const summaryId = (await row.getAttribute('data-testid'))!.replace('impact-row-', '')
  await page.getByTestId(`impact-regenerate-${summaryId}`).click()
  await expect(page.getByTestId('impact-message')).toContainText('按历史版本判定')
})

test('血缘页：读取摘要落入待确认台账，确认后接力生成可回查的业务记录', async ({ page }) => {
  const browserErrors: string[] = []
  page.on('pageerror', (e) => browserErrors.push(e.message))
  page.on('response', (r) => {
    if (r.url().includes('/api/') && r.status() >= 400) browserErrors.push(`${r.status()} ${r.url()}`)
  })
  await page.goto('/lineage')
  await page.getByTestId('open-ledger').click()
  await expect(page.getByTestId('ledger-panel')).toBeVisible()

  await page.getByTestId('ledger-window').selectOption('2026-09-01')
  await page.getByTestId('ledger-push').click()
  await expect(page.getByTestId('ledger-message')).toContainText('待确认台账')
  await expect(page.getByTestId('ledger-table').locator('tbody tr').first()).toBeVisible()

  await page.getByTestId('ledger-confirm').click()
  await expect(page.getByTestId('ledger-message')).toContainText('已确认')
  await page.getByTestId('ledger-relay').click()
  await expect(page.getByTestId('ledger-message')).toContainText('业务记录')
  await expect(page.getByTestId('ledger-record-count')).not.toHaveText('0')
  await expect(page.getByTestId('ledger-lineage-count')).not.toHaveText('0')
  await expect(page.getByTestId('ledger-status')).toHaveText('已接力')

  // 第二次接力不重复生成
  await page.getByTestId('ledger-relay').click()
  await expect(page.getByTestId('ledger-message')).toContainText('已生成')

  // 去重页按摘要回查血缘业务记录
  await openImpact(page)
  const row = page.locator('[data-testid^="impact-row-"]').filter({ hasText: '2026-09-01' }).first()
  const summaryId = (await row.getAttribute('data-testid'))!.replace('impact-row-', '')
  await page.getByTestId(`impact-lookup-${summaryId}`).click()
  await expect(page.getByTestId('impact-lookup-result')).toBeVisible()
  await expect(page.getByTestId('impact-lookup-result')).toContainText('LINE-DEDUP-')

  expect(browserErrors).toEqual([])
})
