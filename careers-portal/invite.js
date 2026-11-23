#!/usr/bin/env node
"use strict";
/* HR command line.
   node invite.js new --name "Aisyah Rahman" --email a@x.com --position "Solar PV Engineer" --ref EE-2026-07 [--stage application|offer|onboarding] [--days 14]
   node invite.js list
   node invite.js revoke <token>
   node invite.js extend <token> --days 7                                                          */
const inv = require("./lib/invites.js");
const BASE = process.env.BASE_URL || "https://www.ecoconsultancy.services";
const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(`--${k}`); return i > -1 ? args[i + 1] : d; };
const cmd = args[0];

if (cmd === "new") {
  const need = ["name", "email", "position"].filter((k) => !opt(k));
  if (need.length) { console.error("Missing: " + need.map((k) => `--${k}`).join(", ")); process.exit(1); }
  const stage = opt("stage", "application");
  if (!["application", "offer", "onboarding"].includes(stage)) { console.error("stage must be application | offer | onboarding"); process.exit(1); }
  const r = inv.create({ name: opt("name"), email: opt("email"), position: opt("position"), ref: opt("ref", ""), stage, days: Number(opt("days", 14)) });
  console.log(`\nInvite created for ${r.invite.name} (${stage})`);
  console.log(`  Link      : ${BASE}/careers/apply/${r.token}`);
  console.log(`  Password  : ${r.password}`);
  console.log(`  Expires   : ${r.invite.expires}\n`);
  console.log("Send the link by email and the password by a SEPARATE channel (WhatsApp / SMS / phone). Never put both in one message.\n");
} else if (cmd === "list") {
  console.table(inv.list());
} else if (cmd === "revoke") {
  console.log(inv.revoke(args[1]) ? "Revoked." : "Token not found.");
} else if (cmd === "extend") {
  const e = inv.extend(args[1], Number(opt("days", 7)));
  console.log(e ? `Extended to ${e}` : "Token not found.");
} else {
  console.log("Usage: node invite.js new|list|revoke|extend  (see header of this file)");
}
