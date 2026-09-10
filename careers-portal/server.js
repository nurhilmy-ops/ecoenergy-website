"use strict";
/* EcoEnergy Consultancy Sdn Bhd — invited-candidate recruitment portal.
   Node 20+ · Fastify 4.  Mount at https://www.ecoconsultancy.services/careers/apply/<token>  */
const path = require("path");
const fs = require("fs");
const crypto = require("crypto");
const bcrypt = require("bcryptjs");
const Fastify = require("fastify");
const { forms, stages } = require("./public/schema.js");
const { renderFormPdf } = require("./lib/pdf.js");
const invites = require("./lib/invites.js");

const ENV = process.env;
const PORT = Number(ENV.PORT || 3000);
const SESSION_SECRET = ENV.SESSION_SECRET || (() => { console.warn("SESSION_SECRET not set — using a random secret; sessions reset on restart"); return crypto.randomBytes(32).toString("hex"); })();
const DATA_DIR = ENV.DATA_DIR || path.join(__dirname, "data");
const SUB_DIR = path.join(DATA_DIR, "submissions");
const SESSION_TTL_MIN = Number(ENV.SESSION_TTL_MIN || 240);
const HR_EMAIL = ENV.HR_EMAIL || "contact@ecoconsultancy.services";
fs.mkdirSync(SUB_DIR, { recursive: true });

const app = Fastify({ logger: true, trustProxy: true, bodyLimit: 2 * 1024 * 1024 });

async function main() {
await app.register(require("@fastify/cookie"), { secret: SESSION_SECRET });
await app.register(require("@fastify/rate-limit"), { global: false });
await app.register(require("@fastify/static"), { root: path.join(__dirname, "public"), prefix: "/careers/static/", decorateReply: false });

// Every response: never indexed, never cached, strict framing.
app.addHook("onSend", async (req, reply) => {
  reply.header("X-Robots-Tag", "noindex, nofollow, noarchive");
  reply.header("Cache-Control", "no-store");
  reply.header("X-Frame-Options", "DENY");
  reply.header("X-Content-Type-Options", "nosniff");
  reply.header("Referrer-Policy", "no-referrer");
});

app.get("/robots.txt", async (req, reply) => reply.type("text/plain").send("User-agent: *\nDisallow: /careers/apply\nDisallow: /careers/api\nDisallow: /careers/static\n"));
app.get("/healthz", async () => ({ ok: true }));

const notFound = (reply) => reply.code(404).type("text/html").send("<!doctype html><meta name=robots content=noindex><title>Not found</title><p style='font-family:sans-serif;padding:40px'>This link is not valid or has expired.</p>");

const session = {
  read(req) {
    const raw = req.cookies.ee_sess; if (!raw) return null;
    const u = req.unsignCookie(raw); if (!u.valid) return null;
    try { const s = JSON.parse(u.value); return s.exp > Date.now() ? s : null; } catch { return null; }
  },
  write(reply, token) {
    reply.setCookie("ee_sess", JSON.stringify({ token, exp: Date.now() + SESSION_TTL_MIN * 60000 }), {
      path: "/careers", httpOnly: true, sameSite: "strict", secure: ENV.NODE_ENV === "production", signed: true, maxAge: SESSION_TTL_MIN * 60,
    });
  },
};

// 1. Gate page. Unknown or expired token → identical 404 (no enumeration signal).
app.get("/careers/apply/:token", async (req, reply) => {
  const inv = invites.get(req.params.token);
  if (!inv || invites.expired(inv)) return notFound(reply);
  return reply.type("text/html").send(fs.readFileSync(path.join(__dirname, "public", "apply.html")));
});

// 2. Password check. 5 attempts per 15 minutes per IP+token, then lock-out.
app.post("/careers/api/verify", { config: { rateLimit: { max: 5, timeWindow: "15 minutes", keyGenerator: (req) => `${req.ip}:${(req.body && req.body.token) || ""}` } } }, async (req, reply) => {
  const { token, password } = req.body || {};
  const inv = invites.get(token);
  await new Promise((r) => setTimeout(r, 400)); // flat delay
  if (!inv || invites.expired(inv) || !password || !(await bcrypt.compare(String(password), inv.hash))) {
    invites.recordAttempt(token, false);
    return reply.code(401).send({ error: "Incorrect password or invalid link." });
  }
  invites.recordAttempt(token, true);
  session.write(reply, token);
  return { ok: true };
});

const requireSession = (req, reply) => {
  const s = session.read(req);
  const inv = s && invites.get(s.token);
  if (!inv || invites.expired(inv)) { reply.code(401).send({ error: "Session expired. Enter your password again." }); return null; }
  return { s, inv };
};

// 3. Invite metadata for the signed-in candidate (drives prefills and which forms show).
app.get("/careers/api/invite", async (req, reply) => {
  const ctx = requireSession(req, reply); if (!ctx) return;
  const { inv, s } = ctx;
  const done = invites.submittedForms(s.token);
  return { name: inv.name, email: inv.email, position: inv.position, ref: inv.ref || "", stage: inv.stage, forms: stages[inv.stage], submitted: done, expires: inv.expires };
});

// ---- validation from schema ----
function validate(form, data) {
  const errors = [];
  const has = (v) => !(v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length));
  for (const sec of form.sections) for (const f of sec.fields) {
    const v = data[f.id];
    if (f.showIf) { const [k, want] = Object.entries(f.showIf)[0]; if (data[k] !== want) continue; }
    if (f.req) {
      if (f.type === "table" || f.type === "blocks") {
        const rows = Array.isArray(v) ? v.filter((r) => r && Object.values(r).some(has)) : [];
        if (rows.length < (f.min || 1)) errors.push(`${f.label}: at least ${f.min || 1} entr${(f.min || 1) > 1 ? "ies" : "y"} required`);
        rows.forEach((r, i) => f.columns.filter((c) => c.req).forEach((c) => { if (!has(r[c.id])) errors.push(`${f.label} #${i + 1}: ${c.label} required`); }));
      } else if (f.type === "yn") { if (!v || !["Yes", "No"].includes(v.answer)) errors.push(`Answer required: ${f.label.slice(0, 60)}…`); }
      else if (f.type === "consent") { if (v !== true) errors.push("Declaration / consent must be confirmed"); }
      else if (f.type === "sign") { if (!v || !has(v.name)) errors.push("Typed signature required"); }
      else if (!has(v)) errors.push(`${f.label} is required`);
    }
    if (f.type === "email" && has(v) && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(v))) errors.push("Email address is not valid");
    if (f.type === "radio" && has(v) && !f.options.includes(v)) errors.push(`${f.label}: invalid option`);
    if (f.type === "select" && has(v) && !f.options.includes(v)) errors.push(`${f.label}: invalid option`);
    if (["text", "tel", "email"].includes(f.type) && has(v) && String(v).length > 300) errors.push(`${f.label}: too long`);
    if (f.type === "textarea" && has(v) && String(v).length > 4000) errors.push(`${f.label}: too long`);
  }
  return errors;
}

// 4. Submit one form: validate → PDF → store → email HR.
app.post("/careers/api/submit", { config: { rateLimit: { max: 20, timeWindow: "1 hour" } } }, async (req, reply) => {
  const ctx = requireSession(req, reply); if (!ctx) return;
  const { inv, s } = ctx;
  const { formId, data } = req.body || {};
  const form = forms[formId];
  if (!form || !stages[inv.stage].includes(formId)) return reply.code(400).send({ error: "This form is not part of your invitation." });
  if (typeof data !== "object" || !data) return reply.code(400).send({ error: "No data" });
  const errors = validate(form, data);
  if (errors.length) return reply.code(422).send({ error: "Please complete the highlighted items.", errors });

  const now = new Date();
  const kl = now.toLocaleString("en-GB", { timeZone: "Asia/Kuala_Lumpur", hour12: false });
  const ref = `${form.code}-${now.toISOString().slice(0, 10).replace(/-/g, "")}-${crypto.randomBytes(3).toString("hex").toUpperCase()}`;
  const meta = { ref, submittedAt: kl, ip: req.ip, ua: String(req.headers["user-agent"] || "").slice(0, 80) };
  // stamp signatures server-side (client timestamp is not trusted)
  for (const sec of form.sections) for (const f of sec.fields) if (f.type === "sign" && data[f.id]) data[f.id] = { name: String(data[f.id].name || "").slice(0, 120), at: kl };

  const pdf = await renderFormPdf({ form, data, invite: inv, meta });
  const dir = path.join(SUB_DIR, s.token); fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, `${ref}.pdf`), pdf);
  fs.writeFileSync(path.join(dir, `${ref}.json`), JSON.stringify({ meta, invite: { name: inv.name, email: inv.email, position: inv.position, stage: inv.stage }, formId, data }, null, 2));
  invites.recordSubmission(s.token, { formId, code: form.code, ref, at: now.toISOString() });

  // Email HR (optional: needs SMTP_* env). Failure here must not lose the submission.
  let mailed = false;
  if (ENV.SMTP_HOST) {
    try {
      const nodemailer = require("nodemailer");
      const t = nodemailer.createTransport({ host: ENV.SMTP_HOST, port: Number(ENV.SMTP_PORT || 587), secure: ENV.SMTP_SECURE === "true", auth: ENV.SMTP_USER ? { user: ENV.SMTP_USER, pass: ENV.SMTP_PASS } : undefined });
      await t.sendMail({ from: ENV.SMTP_FROM || `EcoEnergy Careers <${HR_EMAIL}>`, to: HR_EMAIL, replyTo: inv.email,
        subject: `[Recruitment] ${form.code} received — ${inv.name} — ${inv.position} (${ref})`,
        text: `${inv.name} submitted ${form.title} for ${inv.position}.\nRef: ${ref}\nTime: ${kl} (KL)\n\nThe PDF is attached and also stored at data/submissions/${s.token}/${ref}.pdf.\nDo not forward outside HR: contains personal data under PDPA 2010.`,
        attachments: [{ filename: `${ref}.pdf`, content: pdf }] });
      mailed = true;
    } catch (e) { req.log.error({ err: e }, "HR notification email failed"); }
  }
  return { ok: true, ref, mailed, pdf: `/careers/api/pdf/${ref}` };
});

// 5. Candidate downloads their own copy (session-bound to the same invite).
app.get("/careers/api/pdf/:ref", async (req, reply) => {
  const ctx = requireSession(req, reply); if (!ctx) return;
  const ref = String(req.params.ref).replace(/[^A-Z0-9-]/g, "");
  const file = path.join(SUB_DIR, ctx.s.token, `${ref}.pdf`);
  if (!fs.existsSync(file)) return reply.code(404).send({ error: "Not found" });
  return reply.type("application/pdf").header("Content-Disposition", `attachment; filename="EcoEnergy-${ref}.pdf"`).send(fs.createReadStream(file));
});

app.post("/careers/api/logout", async (req, reply) => { reply.clearCookie("ee_sess", { path: "/careers" }); return { ok: true }; });

app.setNotFoundHandler((req, reply) => notFound(reply));

await app.listen({ port: PORT, host: "0.0.0.0" });
}
main().catch((e) => { console.error(e); process.exit(1); });
