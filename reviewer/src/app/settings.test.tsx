import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";
import { I18nProvider, useI18n } from "./i18n";
import { ThemeProvider, useTheme } from "./theme";

function SettingsHarness() {
  const { locale, setLocale, t } = useI18n();
  const { resolvedTheme, setTheme } = useTheme();
  return (
    <div>
      <span>{t("transport.play")}</span>
      <span>{locale}</span>
      <span>{resolvedTheme}</span>
      <button onClick={() => setLocale(locale === "zh" ? "en" : "zh")}>locale</button>
      <button onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}>theme</button>
    </div>
  );
}

describe("reviewer settings", () => {
  beforeEach(() => {
    window.localStorage.clear();
    document.documentElement.className = "";
    document.documentElement.removeAttribute("data-theme");
  });

  it("switches and persists the same en/zh locale pair as the website", async () => {
    const user = userEvent.setup();
    render(
      <I18nProvider initialLocale="zh">
        <ThemeProvider initialTheme="dark">
          <SettingsHarness />
        </ThemeProvider>
      </I18nProvider>,
    );

    expect(screen.getByText("播放")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "locale" }));
    expect(screen.getByText("Play")).toBeInTheDocument();
    expect(window.localStorage.getItem("openbbq-review-locale")).toBe("en");
    expect(document.documentElement.lang).toBe("en");
  });

  it("switches light and dark themes and persists the choice", async () => {
    const user = userEvent.setup();
    render(
      <I18nProvider initialLocale="en">
        <ThemeProvider initialTheme="dark">
          <SettingsHarness />
        </ThemeProvider>
      </I18nProvider>,
    );

    expect(document.documentElement.classList.contains("dark")).toBe(true);
    await user.click(screen.getByRole("button", { name: "theme" }));
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem("openbbq-review-theme")).toBe("light");
  });
});
