import adapter from "waku/adapters/cloudflare";
import { createRouter } from "fumapress/router";
import { fsRouterFn } from "fumapress/router/fs";
import pressConfig from "../press.config";

const router = await createRouter(pressConfig);
const modules = import.meta.glob("./pages/**/*.{ts,tsx,js,jsx}", {
  base: "/src",
});
const pages = router.createPages(fsRouterFn(modules));
const middlewareFns = router.createMiddlewares();
const cloudflareAdapter = router.patchAdapter(adapter);

export default cloudflareAdapter(pages, {
  middlewareFns,
  static: true,
});
