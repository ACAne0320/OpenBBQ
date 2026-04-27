import { expect, test, type Page } from "@playwright/test";

async function expectNoHorizontalDocumentOverflow(page: Page) {
  const dimensions = await page.evaluate(() => {
    const root = document.documentElement;
    const body = document.body;

    return {
      clientWidth: root.clientWidth,
      scrollWidth: Math.max(root.scrollWidth, body.scrollWidth)
    };
  });

  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.clientWidth + 1);
}

async function continueFromSourceToWorkflow(page: Page) {
  await page.goto("/");
  await page.getByLabel("Video link").fill("https://example.com/sample-video.mp4");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("heading", { name: "Arrange workflow" })).toBeVisible();
}

async function continueFromWorkflowToMonitor(page: Page) {
  await continueFromSourceToWorkflow(page);
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByText("Task monitor")).toBeVisible();
}

test("source import renders the URL and local file targets", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Choose a source" })).toBeVisible();
  await expect(page.getByLabel("Video link")).toBeVisible();
  await expect(page.locator('label[for="source-local-file"]')).toBeVisible();
  await expect(page.getByText("Drag/drop or click to choose a local file")).toBeVisible();
  await expectNoHorizontalDocumentOverflow(page);
});

test("workflow page renders after entering a valid URL", async ({ page }) => {
  await continueFromSourceToWorkflow(page);

  await expect(page.getByText("Selected step parameters")).toBeVisible();
  await expect(page.getByRole("button", { name: "Continue" })).toBeVisible();
});

test("task monitor renders the failed checkpoint state", async ({ page }) => {
  await continueFromWorkflowToMonitor(page);

  await expect(page.getByText("Runtime log")).toBeVisible();
  await expect(page.getByText(/provider returned rate limit/i)).toBeVisible();
  await expect(page.getByRole("alert").getByRole("button", { name: "Retry checkpoint" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Retry checkpoint" })).toHaveCount(1);
  await expectNoHorizontalDocumentOverflow(page);
});

test("results review renders from navigation without manual save controls", async ({ page }) => {
  await continueFromWorkflowToMonitor(page);
  await page.getByRole("button", { name: "Results" }).click();

  await expect(page.getByText("Review results")).toBeVisible();
  await expect(page.getByLabel("Video preview", { exact: true })).toBeVisible();
  await expect(page.getByText("Audio loudness")).toBeVisible();
  await expect(page.getByText("Editable segments")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save changes" })).toHaveCount(0);
  await expect(page.getByText("Save changes")).toHaveCount(0);
  await expectNoHorizontalDocumentOverflow(page);
});
