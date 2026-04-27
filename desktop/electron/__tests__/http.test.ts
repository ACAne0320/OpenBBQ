// @vitest-environment node
import { describe, expect, it, vi } from "vitest";

import { requestJson } from "../http";
import type { SidecarConnection } from "../sidecar";

const connection: SidecarConnection = {
  host: "127.0.0.1",
  port: 53124,
  pid: 12345,
  token: "secret",
  baseUrl: "http://127.0.0.1:53124"
};

describe("requestJson", () => {
  it("adds bearer auth and unwraps success envelopes", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: { id: "run_1" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    const result = await requestJson<{ id: string }>(connection, "/runs/run_1", {}, fetchImpl);

    expect(result).toEqual({ id: "run_1" });
    expect(fetchImpl).toHaveBeenCalledWith(
      "http://127.0.0.1:53124/runs/run_1",
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: "Bearer secret" })
      })
    );
  });

  it("normalizes API error envelopes", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: false, error: { code: "not_found", message: "run missing", details: {} } }), {
        status: 404,
        headers: { "Content-Type": "application/json" }
      })
    );

    await expect(requestJson(connection, "/runs/missing", {}, fetchImpl)).rejects.toMatchObject({
      code: "not_found",
      message: "run missing",
      status: 404
    });
  });

  it("normalizes network failures", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError("fetch failed"));

    await expect(requestJson(connection, "/runs/run_1", {}, fetchImpl)).rejects.toMatchObject({
      code: "sidecar_unreachable"
    });
  });

  it("sends JSON request bodies", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ ok: true, data: { run_id: "run_1" } }), {
        status: 200,
        headers: { "Content-Type": "application/json" }
      })
    );

    await requestJson(connection, "/quickstart/subtitle/youtube", { method: "POST", body: { url: "https://example.test/v" } }, fetchImpl);

    expect(fetchImpl.mock.calls[0][1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({ url: "https://example.test/v" })
    });
  });
});
