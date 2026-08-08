import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./app/App";
import { TooltipProvider } from "./components/ui/tooltip";
import { I18nProvider } from "./app/i18n";
import { ThemeProvider } from "./app/theme";
import "@fontsource-variable/geist/index.css";
import "@fontsource-variable/jetbrains-mono/index.css";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <I18nProvider>
      <ThemeProvider>
        <TooltipProvider delay={300}>
          <App />
        </TooltipProvider>
      </ThemeProvider>
    </I18nProvider>
  </StrictMode>,
);
