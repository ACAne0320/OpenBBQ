# OpenBBQ Website

This is the OpenBBQ documentation and showcase site. It is built with Fumapress, Waku, and Fumadocs MDX, then deployed as static assets on Cloudflare.

## Development

```sh
pnpm install
pnpm dev
```

The localized routes start at `/en` and `/zh`. The root route provides a language gateway.

## Validation

```sh
pnpm types:check
pnpm build
pnpm exec wrangler deploy --dry-run
```

## Cloudflare

Set the canonical production origin before building:

```sh
PUBLIC_SITE_URL=https://openbbq.acane.dev pnpm build
```

Preview the generated `dist/public` assets with the Cloudflare runtime:

```sh
pnpm preview:cloudflare
```

Deploy after authenticating Wrangler:

```sh
pnpm deploy
```
