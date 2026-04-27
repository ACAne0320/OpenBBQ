import { createMockClient, type OpenBBQClient } from "./apiClient";
import { createDesktopClient } from "./desktopClient";

export function createDefaultClient(): OpenBBQClient {
  if (typeof window !== "undefined" && window.openbbq) {
    return createDesktopClient(window.openbbq);
  }

  return createMockClient();
}
