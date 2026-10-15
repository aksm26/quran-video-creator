import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";
import worker, { _resetToken } from "./worker.js";

const env = { QF_OAUTH: "https://oauth", QF_API: "https://api", QF_CLIENT_ID: "id", QF_CLIENT_SECRET: "secret" };
let calls, apiStatus;

beforeEach(() => {
  _resetToken();
  calls = [];
  apiStatus = [200];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url, init });
    if (url.startsWith("https://oauth")) return new Response(JSON.stringify({ access_token: `t${calls.length}`, expires_in: 3600 }));
    return new Response("{}", { status: apiStatus.shift() ?? 200 });
  };
});

const get = (path, method = "GET") => worker.fetch(new Request(`https://proxy${path}`, { method }), env);

test("forwards allowed paths with auth headers and reuses the token", async () => {
  assert.equal((await get("/v4/verses/by_chapter/2?words=true&page=1")).status, 200);
  assert.equal((await get("/v4/chapters")).status, 200);
  const api = calls.filter((c) => c.url.startsWith("https://api"));
  assert.equal(api[0].url, "https://api/content/api/v4/verses/by_chapter/2?words=true&page=1");
  assert.equal(api[0].init.headers["x-client-id"], "id");
  assert.equal(api[0].init.headers["x-auth-token"], "t1");
  assert.equal(calls.filter((c) => c.url.startsWith("https://oauth")).length, 1);
});

test("rejects anything outside the allowlist and non-GET", async () => {
  for (const p of ["/v4/foo", "/v4/chapters/../users", "/oauth2/token", "/v4/chapters/1/info"]) assert.equal((await get(p)).status, 404, p);
  assert.equal((await get("/v4/chapters", "POST")).status, 405);
  assert.equal(calls.length, 0);
});

test("a 401 gets a fresh token and one retry", async () => {
  apiStatus = [401, 200];
  assert.equal((await get("/v4/chapter_recitations/7/112")).status, 200);
  assert.equal(calls.filter((c) => c.url.startsWith("https://oauth")).length, 2);
});

test("rate limit is enforced when the binding exists", async () => {
  const r = await worker.fetch(new Request("https://proxy/v4/chapters"), { ...env, LIMITER: { limit: async () => ({ success: false }) } });
  assert.equal(r.status, 429);
});
