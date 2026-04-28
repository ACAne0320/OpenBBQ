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
  await expectNoHorizontalDocumentOverflow(page);
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
  await expect(page.getByText("Timeline")).toBeVisible();
  await expect(page.getByText("Editable segments")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save changes" })).toHaveCount(0);
  await expect(page.getByText("Save changes")).toHaveCount(0);
  await expectNoHorizontalDocumentOverflow(page);
});

test("results review keeps the timeline scroll local without resizing the video column", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "chromium-desktop", "Two-column alignment is desktop-only.");

  await continueFromWorkflowToMonitor(page);
  await page.getByRole("button", { name: "Results" }).click();
  await expect(page.getByText("Review results")).toBeVisible();

  const metrics = await page.evaluate(() => {
    function byLabel(label: string) {
      const element = [...document.querySelectorAll<HTMLElement>("[aria-label]")].find(
        (node) => node.getAttribute("aria-label") === label
      );

      if (!element) {
        throw new Error(`Missing element with aria-label: ${label}`);
      }

      const rect = element.getBoundingClientRect();
      return {
        height: rect.height,
        left: rect.left,
        top: rect.top,
        width: rect.width
      };
    }

    return {
      layout: byLabel("Results review layout"),
      segmentList: byLabel("Segment list"),
      timeline: byLabel("Timeline panel"),
      video: byLabel("Video preview"),
      videoPanel: byLabel("Video preview panel"),
      viewportHeight: window.innerHeight,
      viewportWidth: window.innerWidth,
      scrollHeight: document.documentElement.scrollHeight,
      scrollWidth: document.documentElement.scrollWidth
    };
  });

  expect(metrics.videoPanel.width).toBeLessThan(metrics.layout.width * 0.65);
  expect(metrics.video.width).toBeLessThan(metrics.layout.width * 0.65);
  expect(metrics.timeline.width).toBeLessThan(metrics.layout.width * 0.65);
  expect(metrics.segmentList.left).toBeGreaterThan(metrics.videoPanel.left + metrics.videoPanel.width);
  expect(metrics.scrollWidth).toBeLessThanOrEqual(metrics.viewportWidth + 1);
  expect(metrics.scrollHeight).toBeLessThanOrEqual(metrics.viewportHeight + 24);
});
