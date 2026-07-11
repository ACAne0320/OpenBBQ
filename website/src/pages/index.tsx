import type { RouteConfig } from "fumapress";

export function getConfig() {
  return {
    autoI18n: false,
    render: "static",
  } satisfies RouteConfig;
}

export default function LanguageGateway() {
  return (
    <div className="bbq-language-gateway">
      <main>
        <p className="bbq-kicker">OpenBBQ</p>
        <h1 className="bbq-title" style={{ color: "white", fontSize: "clamp(2.5rem, 8vw, 5rem)" }}>
          Choose your language
        </h1>
        <div className="bbq-actions">
          <a className="bbq-button bbq-button-primary" href="/en">English</a>
          <a className="bbq-button" style={{ color: "white" }} href="/zh">简体中文</a>
        </div>
      </main>
    </div>
  );
}
