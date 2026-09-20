"use strict";
const PDFDocument = require("pdfkit");
const path = require("path");
const fs = require("fs");

const NAVY = "#0F2742", GOLD = "#B8841F", SLATE = "#5A6B7C", GREY = "#E9EDF2", LINE = "#B0BAC6";
const LOGO = path.join(__dirname, "..", "public", "assets", "logo.png");
const MARK = path.join(__dirname, "..", "public", "assets", "mark.png");

const fmt = (v) => (v === undefined || v === null || v === "" ? "—" : Array.isArray(v) ? v.join(", ") : String(v));

/** Render one form submission to a PDF buffer. */
function renderFormPdf({ form, data, invite, meta }) {
  return new Promise((resolve, reject) => {
    const doc = new PDFDocument({ size: "A4", margins: { top: 90, bottom: 60, left: 50, right: 50 }, info: { Title: `${form.code} ${form.title}`, Author: "EcoEnergy Consultancy Sdn Bhd" } });
    const chunks = [];
    doc.on("data", (c) => chunks.push(c));
    doc.on("end", () => resolve(Buffer.concat(chunks)));
    doc.on("error", reject);

    const W = doc.page.width - 100;
    const header = () => {
      if (fs.existsSync(LOGO)) doc.image(LOGO, 50, 28, { height: 30 });
      doc.font("Helvetica-Bold").fontSize(8).fillColor(NAVY).text("EcoEnergy Consultancy Sdn Bhd", 300, 28, { width: 245, align: "right", lineBreak: false });
      doc.font("Helvetica").fontSize(7).fillColor(SLATE).text("Human Resources — Recruitment Forms", 300, 39, { width: 245, align: "right", lineBreak: false });
      doc.font("Helvetica-Bold").fontSize(7).fillColor(GOLD).text(`${form.code}  ·  Ref ${meta.ref}`, 300, 49, { width: 245, align: "right", lineBreak: false });
      doc.moveTo(50, 66).lineTo(50 + W, 66).lineWidth(1.2).strokeColor(GOLD).stroke();
    };
    const footer = () => {
      const y = doc.page.height - 45;
      const mb = doc.page.margins.bottom; doc.page.margins.bottom = 0; // footer sits below the content margin
      doc.moveTo(50, y).lineTo(50 + W, y).lineWidth(0.4).strokeColor(LINE).stroke();
      doc.font("Helvetica").fontSize(6.5).fillColor(SLATE)
        .text("EcoEnergy Consultancy Sdn Bhd · Level 21 & 22, Menara Merdeka 118, Presint Merdeka 118, 50118 Kuala Lumpur · CONFIDENTIAL: personal data (PDPA 2010)", 50, y + 5, { width: W, lineBreak: false, ellipsis: true });
      doc.page.margins.bottom = mb;
    };
    header(); footer(); doc.on("pageAdded", () => { header(); footer(); doc.y = 80; doc.x = 50; });

    const ensure = (h) => { if (doc.y + h > doc.page.height - 70) { doc.addPage(); } };

    // Title block
    doc.font("Helvetica-Bold").fontSize(17).fillColor(NAVY).text(form.title, 50, 78, { lineBreak: false });
    const tw = doc.widthOfString(form.title);
    doc.fontSize(9).fillColor(GOLD).text(form.code, 50 + tw + 10, 85, { lineBreak: false });
    doc.font("Helvetica-Oblique").fontSize(8.5).fillColor(SLATE).text(form.bm, 50, 100, { lineBreak: false });
    doc.y = 116; doc.x = 50;
    doc.font("Helvetica").fontSize(8).fillColor("#333")
      .text(`Candidate: ${invite.name}   ·   Position: ${invite.position}${invite.ref ? "   ·   Advert ref: " + invite.ref : ""}`);
    doc.text(`Submitted ${meta.submittedAt} (Asia/Kuala_Lumpur)   ·   Submission ref ${meta.ref}`);
    doc.moveDown(0.6);

    const sectionBar = (t) => {
      ensure(40);
      const y0 = doc.y + 4;
      doc.rect(50, y0, W, 15).fill(NAVY);
      doc.font("Helvetica-Bold").fontSize(8).fillColor("#FFFFFF").text(t.toUpperCase(), 56, y0 + 4, { lineBreak: false });
      doc.y = y0 + 20; doc.x = 50;
    };
    const kv = (label, value, wide) => {
      const lw = 170;
      const txt = fmt(value);
      doc.font("Helvetica-Bold").fontSize(7.5); const lh = doc.heightOfString(label, { width: lw - 12 });
      doc.font("Helvetica").fontSize(9); const vh = doc.heightOfString(txt, { width: W - lw - 12 });
      const h = Math.max(lh, vh, 12) + 8;
      ensure(h + 2);
      const y = doc.y;
      doc.rect(50, y, lw, h).fill(GREY);
      doc.rect(50, y, W, h).lineWidth(0.4).strokeColor(LINE).stroke();
      doc.font("Helvetica-Bold").fontSize(7.5).fillColor(NAVY).text(label, 56, y + 4, { width: lw - 12 });
      doc.font("Helvetica").fontSize(9).fillColor("#111").text(txt, 50 + lw + 6, y + 4, { width: W - lw - 12 });
      doc.y = y + h; doc.x = 50;
    };
    const table = (cols, rows) => {
      const cw = cols.map(() => W / cols.length);
      const rowH = (r) => { doc.font("Helvetica").fontSize(8.5); return Math.max(...cols.map((c, i) => doc.heightOfString(fmt(r[c.id]), { width: cw[i] - 8 }))) + 8; };
      ensure(30);
      let y = doc.y;
      doc.font("Helvetica-Bold").fontSize(7.5);
      const hh = Math.max(...cols.map((c, i) => doc.heightOfString(c.label, { width: cw[i] - 8 }))) + 8;
      doc.rect(50, y, W, hh).fill(GREY);
      doc.fillColor(NAVY);
      cols.forEach((c, i) => doc.text(c.label, 50 + cw.slice(0, i).reduce((a, b) => a + b, 0) + 4, y + 4, { width: cw[i] - 8 }));
      doc.y = y + hh;
      doc.font("Helvetica").fontSize(8.5).fillColor("#111");
      (rows.length ? rows : [{}]).forEach((r) => {
        const h = rowH(r);
        ensure(h);
        y = doc.y;
        doc.rect(50, y, W, h).lineWidth(0.4).strokeColor(LINE).stroke();
        cols.forEach((c, i) => doc.text(fmt(r[c.id]), 50 + cw.slice(0, i).reduce((a, b) => a + b, 0) + 4, y + 4, { width: cw[i] - 8 }));
        doc.y = y + h; doc.x = 50;
      });
      doc.moveDown(0.4);
    };
    const para = (t, opts = {}) => { ensure(30); doc.font(opts.bold ? "Helvetica-Bold" : "Helvetica").fontSize(opts.size || 8.5).fillColor(opts.color || "#222").text(t, 50, doc.y, { width: W }); doc.moveDown(0.4); };

    if (form.notice) {
      sectionBar("Notice / Notis");
      form.notice.forEach(([hEn, en, hBm, bm], i) => {
        ensure(60);
        const y = doc.y, half = W / 2 - 6;
        doc.font("Helvetica-Bold").fontSize(7.5).fillColor(NAVY).text(`${i + 1}. ${hEn}`, 50, y, { width: half });
        doc.font("Helvetica").fontSize(7.5).fillColor("#222").text(en, 50, doc.y, { width: half });
        const yEnd = doc.y;
        doc.font("Helvetica-Bold").fontSize(7.5).fillColor(NAVY).text(`${i + 1}. ${hBm}`, 50 + W / 2 + 6, y, { width: half });
        doc.font("Helvetica-Oblique").fontSize(7.5).fillColor("#333").text(bm, 50 + W / 2 + 6, doc.y, { width: half });
        doc.y = Math.max(yEnd, doc.y) + 6; doc.x = 50;
      });
    }

    for (const sec of form.sections) {
      sectionBar(sec.title);
      for (const f of sec.fields) {
        const v = data[f.id];
        switch (f.type) {
          case "table": table(f.columns, Array.isArray(v) ? v : []); break;
          case "blocks":
            (Array.isArray(v) && v.length ? v : [{}]).forEach((b, i) => { para(`${i + 1}.`, { bold: true, color: GOLD, size: 9 }); f.columns.forEach((c) => kv(c.label, b[c.id])); doc.moveDown(0.3); });
            break;
          case "areas": {
            const rows = f.options.map((o) => ({ area: o, tick: v && v[o] && v[o].tick ? "Yes" : "", scale: v && v[o] ? v[o].scale : "" }));
            table([{ id: "area", label: "Area" }, { id: "tick", label: "Experience" }, { id: "scale", label: "Scale / examples" }], rows);
            break;
          }
          case "yn": kv(f.label, v && v.answer ? `${v.answer}${v.details ? " — " + v.details : ""}` : "—", true); break;
          case "consent": case "check": kv(f.label, v ? "Confirmed — Yes" : "Not confirmed", true); break;
          case "sign":
            ensure(50);
            kv("Signature (typed)", v ? `${v.name}` : "—");
            kv("Signed at", v ? `${v.at}  ·  IP ${meta.ip}  ·  UA ${meta.ua}` : "—");
            break;
          default: if (f.showIf && !v) break; kv(f.label, v);
        }
      }
      if (sec.note) { doc.moveDown(0.3); para(sec.note, { size: 7.5, color: SLATE }); }
    }
    footer();
    doc.end();
  });
}

module.exports = { renderFormPdf };
