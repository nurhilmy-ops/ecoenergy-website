"use strict";
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const bcrypt = require("bcryptjs");

const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, "..", "data");
const FILE = path.join(DATA_DIR, "invites.json");
fs.mkdirSync(DATA_DIR, { recursive: true });

const load = () => (fs.existsSync(FILE) ? JSON.parse(fs.readFileSync(FILE, "utf8")) : {});
const save = (db) => fs.writeFileSync(FILE, JSON.stringify(db, null, 2), { mode: 0o600 });

const WORDS = ["Solar", "Hydro", "Grid", "Kedah", "Perak", "Pahang", "Kelip", "Merdeka", "Tenaga", "Cahaya", "Angin", "Sungai", "Bukit", "Sinar", "Pulau", "Langkawi"];
function generatePassword() {
  const pick = () => WORDS[crypto.randomInt(WORDS.length)];
  return `${pick()}-${pick()}-${crypto.randomInt(1000, 9999)}`; // ~34 bits + lock-out; rotate per invite
}

function create({ name, email, position, ref = "", stage = "application", days = 14 }) {
  const db = load();
  const token = crypto.randomBytes(16).toString("base64url");
  const password = generatePassword();
  db[token] = {
    name, email, position, ref, stage,
    hash: bcrypt.hashSync(password, 10),
    created: new Date().toISOString(),
    expires: new Date(Date.now() + days * 86400000).toISOString(),
    attempts: [], submissions: [],
  };
  save(db);
  return { token, password, invite: db[token] };
}

const get = (token) => (token && /^[A-Za-z0-9_-]{20,24}$/.test(token) ? load()[token] || null : null);
const expired = (inv) => new Date(inv.expires).getTime() < Date.now() || inv.revoked === true;
const submittedForms = (token) => (get(token) || { submissions: [] }).submissions.map((s) => s.formId);

function recordAttempt(token, ok) {
  const db = load(); if (!db[token]) return;
  db[token].attempts.push({ at: new Date().toISOString(), ok });
  db[token].attempts = db[token].attempts.slice(-50);
  save(db);
}
function recordSubmission(token, entry) {
  const db = load(); if (!db[token]) return;
  db[token].submissions.push(entry);
  save(db);
}
function revoke(token) { const db = load(); if (db[token]) { db[token].revoked = true; save(db); return true; } return false; }
function extend(token, days) { const db = load(); if (db[token]) { db[token].expires = new Date(Date.now() + days * 86400000).toISOString(); save(db); return db[token].expires; } return null; }
const list = () => Object.entries(load()).map(([token, i]) => ({ token, name: i.name, position: i.position, stage: i.stage, expires: i.expires, revoked: !!i.revoked, submissions: i.submissions.map((s) => s.code).join(", ") }));

module.exports = { create, get, expired, submittedForms, recordAttempt, recordSubmission, revoke, extend, list };
