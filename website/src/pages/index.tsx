import type { RouteConfig } from "fumapress";

export function getConfig() {
  return {
    autoI18n: false,
    render: "static",
  } satisfies RouteConfig;
}

export default function LanguageRedirect() {
  return (
    <html lang="en">
      <head>
        <meta httpEquiv="refresh" content="0;url=/en" />
        <link rel="canonical" href="/en" />
        <script dangerouslySetInnerHTML={{ __html: "window.location.replace('/en')" }} />
        <title>OpenBBQ</title>
      </head>
      <body>
        <p>Redirecting to <a href="/en">OpenBBQ</a>...</p>
      </body>
    </html>
  );
}
