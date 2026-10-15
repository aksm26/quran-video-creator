// Quran Video Creator API proxy (Cloudflare Worker).
// Holds the Quran Foundation client secret so the desktop app never ships it (QF requirement), and forwards only
// the read-only Content API calls the app makes. Secrets: QF_CLIENT_ID, QF_CLIENT_SECRET (`wrangler secret put`).

const ALLOWED = /^\/v4\/(chapters|verses\/by_chapter\/\d{1,3}|chapter_recitations\/\d{1,4}\/\d{1,3}|resources\/(chapter_reciters|translations))$/;

let token = null; // {value, expires} kept per worker instance; QF tokens live an hour and have no refresh token

async function getToken(env, force = false) {
  if (!force && token && Date.now() < token.expires) return token.value;
  const r = await fetch(`${env.QF_OAUTH}/oauth2/token`, {
    method: "POST",
    headers: {
      Authorization: "Basic " + btoa(`${env.QF_CLIENT_ID}:${env.QF_CLIENT_SECRET}`),
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: "grant_type=client_credentials&scope=content",
  });
  if (!r.ok) throw new Error(`token request failed: ${r.status}`);
  const d = await r.json();
  token = { value: d.access_token, expires: Date.now() + (d.expires_in - 60) * 1000 };
  return token.value;
}

function json(status, body) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export default {
  async fetch(request, env) {
    if (request.method !== "GET") return json(405, { message: "GET only" });
    const url = new URL(request.url);
    if (!ALLOWED.test(url.pathname)) return json(404, { message: "not found" });
    if (env.LIMITER) {
      const { success } = await env.LIMITER.limit({ key: request.headers.get("CF-Connecting-IP") || "?" });
      if (!success) return json(429, { message: "too many requests" });
    }
    const target = `${env.QF_API}/content/api${url.pathname}${url.search}`;
    try {
      const call = async (force) => fetch(target, {
        headers: { "x-auth-token": await getToken(env, force), "x-client-id": env.QF_CLIENT_ID },
      });
      let r = await call(false);
      if (r.status === 401) r = await call(true); // token revoked or expired early: get a new one, retry once
      return new Response(r.body, { status: r.status, headers: { "Content-Type": "application/json" } });
    } catch (e) {
      return json(502, { message: `upstream error: ${e.message}` }); // message holds a status code, never a secret
    }
  },
};

export function _resetToken() { token = null; } // tests only
