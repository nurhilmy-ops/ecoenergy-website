/* EcoEnergy Consultancy Sdn Bhd — recruitment form schema.
   Single source of truth: the browser renders the form from it, the server validates and builds the PDF from it. */
(function (root, factory) {
  if (typeof module !== "undefined" && module.exports) module.exports = factory();
  else root.FORM_SCHEMA = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const RE_AREAS = [
    "Utility-scale solar PV (LSS / CRESS / CGPP)", "Rooftop / NEM / SELCO solar", "Floating solar PV",
    "Battery energy storage (BESS)", "Hydropower / mini-hydro", "Waste-to-energy / biomass / biogas",
    "Grid connection & TNB / ST approvals", "Financial modelling / project finance", "Feasibility studies & due diligence",
    "EPC / construction supervision", "Environmental & social (EIA / ESIA)",
  ];
  const YN = ["Yes", "No"];

  const forms = {
    // ------------------------------------------------------------------ HR-REC-01
    application: {
      code: "HR-REC-01", title: "Job Application Form", bm: "Borang Permohonan Jawatan",
      intro: "Complete every section. Attach nothing at this stage: your CV and certificate copies will be requested separately by email so that they are never stored on this page. Do not enter your identity card number, date of birth, bank details or a photograph here; those are collected only after an offer is accepted.",
      sections: [
        { id: "a", title: "A. Position applied for", fields: [
          { id: "position", label: "Position applied for", type: "text", req: true, prefill: "position" },
          { id: "ref", label: "Reference / advert no.", type: "text", prefill: "ref" },
          { id: "location", label: "Preferred work location", type: "text" },
          { id: "start", label: "Earliest available start date", type: "date", req: true },
          { id: "salary", label: "Expected monthly salary (RM)", type: "number", req: true },
          { id: "source", label: "How did you learn of this vacancy?", type: "text" },
          { id: "emptype", label: "Employment type sought", type: "radio", req: true, options: ["Permanent", "Fixed-term contract", "Internship / industrial training", "Part-time"], wide: true },
        ] },
        { id: "b", title: "B. Personal particulars", fields: [
          { id: "fullname", label: "Full name (as per identity document)", type: "text", req: true, wide: true, prefill: "name" },
          { id: "prefname", label: "Preferred name", type: "text" },
          { id: "nationality", label: "Nationality", type: "text", req: true },
          { id: "mobile", label: "Mobile telephone", type: "tel", req: true },
          { id: "email", label: "Email address", type: "email", req: true, prefill: "email" },
          { id: "address", label: "Correspondence address", type: "textarea", req: true, wide: true },
          { id: "rtw", label: "Are you legally entitled to work in Malaysia?", type: "radio", req: true, wide: true,
            options: ["Yes — Malaysian citizen / permanent resident", "Yes — I hold a valid pass", "No / sponsorship required"] },
          { id: "passtype", label: "If you hold a pass: pass type and expiry", type: "text", showIf: { rtw: "Yes — I hold a valid pass" } },
        ], note: "Identity card / passport number, date of birth, dependants and statutory registration numbers are collected only after an offer is accepted (Form HR-REC-06)." },
        { id: "c", title: "C. Education and professional qualifications", fields: [
          { id: "education", label: "Education (highest first)", type: "table", req: true, min: 1, max: 6,
            columns: [
              { id: "inst", label: "Institution" }, { id: "qual", label: "Qualification / programme" }, { id: "field", label: "Field" },
              { id: "years", label: "From – To" }, { id: "result", label: "Result / CGPA" },
            ] },
          { id: "certs", label: "Professional certification / registration (e.g. BEM PE/Ir., SEDA GCPV, PMP, MIEM)", type: "table", max: 6,
            columns: [
              { id: "cert", label: "Certification / registration" }, { id: "no", label: "Registration no." },
              { id: "body", label: "Issuing body" }, { id: "valid", label: "Valid until", kind: "date" },
            ] },
        ] },
        { id: "d", title: "D. Employment history (most recent first)", fields: [
          { id: "employment", label: "Employment", type: "blocks", req: true, min: 1, max: 6,
            columns: [
              { id: "employer", label: "Employer", req: true }, { id: "period", label: "Period (mm/yyyy – mm/yyyy)", req: true },
              { id: "title", label: "Position held", req: true }, { id: "lastpay", label: "Last drawn salary (RM)" },
              { id: "duties", label: "Key responsibilities / projects", kind: "textarea", wide: true },
              { id: "reason", label: "Reason for leaving" }, { id: "notice", label: "Notice period" },
            ] },
        ] },
        { id: "e", title: "E. Technical and project experience", fields: [
          { id: "areas", label: "Areas of hands-on project experience", type: "areas", options: RE_AREAS, wide: true,
            help: "Tick the areas in which you have hands-on project experience and state the approximate scale (MW, number of projects, programme such as LSS, CRESS or NEM)." },
          { id: "areas_other", label: "Other areas (specify)", type: "text", wide: true },
          { id: "software", label: "Software / tools (e.g. PVsyst, HOMER, AutoCAD, Excel modelling, GIS)", type: "text", wide: true },
          { id: "languages", label: "Languages (spoken / written)", type: "text" },
          { id: "licence", label: "Driving licence class (if the role requires site travel)", type: "text" },
        ] },
        { id: "f", title: "F. Referees", fields: [
          { id: "referees", label: "Two professional referees, one of whom should be a recent supervisor", type: "table", req: true, min: 2, max: 3,
            columns: [
              { id: "name", label: "Name", req: true }, { id: "org", label: "Organisation & position", req: true },
              { id: "rel", label: "Relationship to you", req: true }, { id: "contact", label: "Telephone / email", req: true },
            ] },
          { id: "ref_hold", label: "Please do not contact my current employer until an offer has been made and accepted.", type: "check", wide: true },
        ], note: "Referees are contacted only after you authorise it (Form HR-REC-04)." },
        { id: "g", title: "G. Applicant declaration", fields: [
          { id: "decl", type: "consent", req: true, wide: true,
            label: "I declare that the information given in this application is true, complete and accurate to the best of my knowledge. I understand that any false statement or material omission may result in the withdrawal of an offer or, if I am employed, in disciplinary action up to and including dismissal under the Employment Act 1955, section 14." },
          { id: "sign", type: "sign", req: true, wide: true, label: "Type your full name as your signature" },
        ] },
      ],
    },

    // ------------------------------------------------------------------ HR-REC-02
    pdpa: {
      code: "HR-REC-02", title: "Applicant Personal Data Notice & Consent", bm: "Notis Data Peribadi Pemohon & Persetujuan",
      intro: "This notice is issued under section 7 of the Personal Data Protection Act 2010 and is provided in the national language and in English as the Act requires. / Notis ini dikeluarkan di bawah seksyen 7 Akta Perlindungan Data Peribadi 2010 dan disediakan dalam bahasa kebangsaan dan bahasa Inggeris sebagaimana dikehendaki oleh Akta.",
      notice: [
        ["Data user", "EcoEnergy Consultancy Sdn Bhd (\u201cthe Company\u201d) is the data user of the personal data you provide in connection with your application.",
         "Pengguna data", "EcoEnergy Consultancy Sdn Bhd (\u201cSyarikat\u201d) ialah pengguna data bagi data peribadi yang anda berikan berhubung permohonan anda."],
        ["Data collected", "Your name, contact details, nationality and right to work, education, qualifications, employment history, salary information, referees and any other information you supply in your application, CV, interview and assessments. Sensitive personal data (health, religion, political opinion, criminal record) is not requested at application stage; where the Company later requires such data for a specific role it will ask for your explicit consent separately.",
         "Data yang dikumpul", "Nama, butiran hubungan, kewarganegaraan dan hak untuk bekerja, pendidikan, kelayakan, sejarah pekerjaan, maklumat gaji, perujuk dan apa-apa maklumat lain yang anda berikan dalam permohonan, CV, temu duga dan penilaian. Data peribadi sensitif (kesihatan, agama, pendapat politik, rekod jenayah) tidak diminta pada peringkat permohonan; sekiranya Syarikat memerlukan data tersebut bagi jawatan tertentu, persetujuan nyata anda akan diminta secara berasingan."],
        ["Purposes", "To assess your suitability for the position applied for or other suitable vacancies; to verify qualifications and references; to communicate with you about your application; to comply with legal obligations including the Employment Act 1955 and the Immigration Act 1959/63; and, if you are engaged, to form part of your personnel record.",
         "Tujuan", "Untuk menilai kesesuaian anda bagi jawatan yang dipohon atau kekosongan lain yang sesuai; mengesahkan kelayakan dan perujuk; berhubung dengan anda mengenai permohonan; mematuhi kewajipan undang-undang termasuk Akta Kerja 1955 dan Akta Imigresen 1959/63; dan, jika anda dilantik, menjadi sebahagian daripada rekod personel anda."],
        ["Sources", "Directly from you; from referees you nominate; from certification bodies and institutions to verify credentials; and from publicly available professional profiles.",
         "Sumber", "Terus daripada anda; daripada perujuk yang anda namakan; daripada badan pensijilan dan institusi untuk pengesahan kelayakan; dan daripada profil profesional yang tersedia secara awam."],
        ["Disclosure", "Within the Company to persons involved in recruitment; to the Company's professional advisers; to referees and credential-issuing bodies for verification; and to regulators or authorities where required by law. Data may be stored on cloud services located outside Malaysia in accordance with section 129 of the Act.",
         "Pendedahan", "Dalam Syarikat kepada individu yang terlibat dalam pengambilan; kepada penasihat profesional Syarikat; kepada perujuk dan badan pengeluar sijil bagi tujuan pengesahan; dan kepada pengawal selia atau pihak berkuasa apabila dikehendaki oleh undang-undang. Data mungkin disimpan di perkhidmatan awan di luar Malaysia selaras dengan seksyen 129 Akta."],
        ["Your rights", "You may request access to and correction of your personal data, withdraw consent, and limit processing by writing to the Company at the contact below (sections 30, 34 and 38). Providing the data marked as required is necessary; without it the Company cannot assess your application.",
         "Hak anda", "Anda boleh meminta akses kepada dan pembetulan data peribadi anda, menarik balik persetujuan, dan mengehadkan pemprosesan dengan menulis kepada Syarikat di alamat di bawah (seksyen 30, 34 dan 38). Pemberian data yang ditandakan sebagai diperlukan adalah wajib; tanpanya Syarikat tidak dapat menilai permohonan anda."],
        ["Retention", "Data of unsuccessful applicants is retained for up to twelve months after the recruitment exercise closes, then securely destroyed, unless you consent to be considered for future vacancies.",
         "Penyimpanan", "Data pemohon yang tidak berjaya disimpan sehingga dua belas bulan selepas proses pengambilan ditutup, kemudian dimusnahkan dengan selamat, melainkan anda bersetuju untuk dipertimbangkan bagi kekosongan akan datang."],
        ["Contact", "HR / Data Protection contact: contact@ecoconsultancy.services, +60 3 2783 4400, Level 21 & 22, Menara Merdeka 118, Presint Merdeka 118, 50118 Kuala Lumpur.",
         "Hubungi", "Pegawai HR / Perlindungan Data: contact@ecoconsultancy.services, +60 3 2783 4400, Level 21 & 22, Menara Merdeka 118, Presint Merdeka 118, 50118 Kuala Lumpur."],
      ],
      sections: [
        { id: "consent", title: "Consent / Persetujuan", fields: [
          { id: "consent", type: "consent", req: true, wide: true,
            label: "I confirm that I have read and understood this notice and I consent to the Company processing my personal data for the purposes described. / Saya mengesahkan bahawa saya telah membaca dan memahami notis ini dan saya bersetuju Syarikat memproses data peribadi saya bagi tujuan yang dinyatakan." },
          { id: "future", type: "check", wide: true,
            label: "I also consent to my data being retained for consideration for future vacancies (optional). / Saya juga bersetuju data saya disimpan untuk pertimbangan kekosongan akan datang (pilihan)." },
          { id: "sign", type: "sign", req: true, wide: true, label: "Type your full name as your signature / Taip nama penuh anda sebagai tandatangan" },
        ] },
      ],
    },

    // ------------------------------------------------------------------ HR-REC-05 (conditional-offer stage)
    declaration: {
      code: "HR-REC-05", title: "Pre-Employment Declaration", bm: "Perakuan Pra-Pekerjaan",
      intro: "This form is issued only with a conditional offer of employment. Some questions concern sensitive personal data as defined in the Personal Data Protection Act 2010, section 4. You are asked for it because it is directly related to the inherent requirements of the role or to the Company's legal obligations, and it is processed only with your explicit consent under section 40. If a question does not apply, answer No.",
      sections: [
        { id: "a", title: "A. Conflicts of interest and business interests", fields: [
          { id: "ci1", type: "yn", req: true, wide: true, label: "Do you, or any immediate family member, hold a directorship, shareholding (other than listed securities below 5%) or other financial interest in any company that develops, supplies to, finances or regulates renewable energy or infrastructure projects in Malaysia?" },
          { id: "ci2", type: "yn", req: true, wide: true, label: "Are you currently engaged in any other employment, consultancy, agency or business activity that you intend to continue?" },
          { id: "ci3", type: "yn", req: true, wide: true, label: "Are you bound by any restrictive covenant, non-compete, non-solicitation or confidentiality obligation to a current or former employer that could affect your work for the Company?" },
          { id: "ci4", type: "yn", req: true, wide: true, label: "Are you related to, or in a close personal relationship with, any director, employee, client or supplier of the Company?" },
          { id: "ci5", type: "yn", req: true, wide: true, label: "Have you ever been a director of a company that was wound up, or been adjudged bankrupt, or are you currently subject to bankruptcy proceedings?" },
        ] },
        { id: "b", title: "B. Professional standing", fields: [
          { id: "ps1", type: "yn", req: true, wide: true, label: "Have you ever been suspended, struck off or disciplined by a professional body (e.g. Board of Engineers Malaysia, SEDA, PMI)?" },
          { id: "ps2", type: "yn", req: true, wide: true, label: "Have you ever been dismissed from employment for misconduct?" },
          { id: "ps3", type: "yn", req: true, wide: true, label: "Do you hold, and will you maintain, every professional registration stated in your application?" },
        ] },
        { id: "c", title: "C. Convictions and proceedings (sensitive personal data — explicit consent required)", fields: [
          { id: "cv1", type: "yn", req: true, wide: true, label: "Have you been convicted of any offence involving dishonesty, fraud, corruption (including under the Malaysian Anti-Corruption Commission Act 2009) or breach of trust, or are any such charges pending against you?" },
          { id: "cv2", type: "yn", req: true, wide: true, label: "Are you currently the subject of any investigation by the Malaysian Anti-Corruption Commission, Securities Commission, Companies Commission or a foreign equivalent?" },
        ], note: "The Company advises Government and private clients on regulated infrastructure and handles confidential commercial information, so integrity is an inherent requirement of every role." },
        { id: "d", title: "D. Fitness for the inherent requirements of the role", fields: [
          { id: "ft1", type: "yn", req: true, wide: true, label: "Is there any reason you would be unable to safely carry out the site-based or travel duties described in the job description, with or without reasonable adjustments?" },
          { id: "ft2", type: "yn", req: true, wide: true, label: "Do you require any adjustment to the workplace or working arrangements to perform the role?" },
          { id: "ft3", type: "yn", req: true, wide: true, label: "Are you willing to undergo a pre-employment medical examination by a registered medical practitioner if the Company requires it for this role?" },
        ], note: "Where the role involves site visits, working at height or extended travel, the Company must consider safety under the Occupational Safety and Health Act 1994, section 15. You are not asked for a diagnosis or medical history." },
        { id: "e", title: "E. Declaration and consent", fields: [
          { id: "decl", type: "consent", req: true, wide: true, label: "I declare that the answers above are true and complete. I give my explicit consent to the Company processing the sensitive personal data in Sections C and D for the purposes stated. I undertake to notify the Company in writing of any change to the matters declared above during my employment. I understand that a false or misleading declaration may lead to withdrawal of the offer or termination of employment." },
          { id: "sign", type: "sign", req: true, wide: true, label: "Type your full name as your signature" },
        ] },
      ],
    },

    // ------------------------------------------------------------------ HR-REC-06 (offer accepted)
    particulars: {
      code: "HR-REC-06", title: "New Employee Particulars Form", bm: "Borang Butiran Pekerja Baharu",
      intro: "Completed on acceptance of offer. This information is needed to prepare your contract of service and to register you with EPF, SOCSO, EIS and LHDN. Copies of your MyKad or passport and pass, and your latest EA form or PCB statement, will be requested by HR through a separate secure channel.",
      sections: [
        { id: "a", title: "A. Identity", fields: [
          { id: "fullname", label: "Full name (as per MyKad / passport)", type: "text", req: true, wide: true, prefill: "name" },
          { id: "idno", label: "MyKad no. / Passport no.", type: "text", req: true },
          { id: "dob", label: "Date of birth", type: "date", req: true },
          { id: "nationality", label: "Nationality", type: "text", req: true },
          { id: "pass", label: "Passport expiry & pass type (non-citizens)", type: "text" },
          { id: "gender", label: "Gender (as per identity document)", type: "select", options: ["Male", "Female"], req: true },
          { id: "marital", label: "Marital status (for tax relief and EPF nomination only)", type: "select", options: ["Single", "Married", "Divorced", "Widowed"] },
          { id: "address", label: "Residential address", type: "textarea", req: true, wide: true },
        ] },
        { id: "b", title: "B. Statutory registrations", fields: [
          { id: "epf", label: "EPF (KWSP) member no.", type: "text" },
          { id: "socso", label: "SOCSO (PERKESO) no.", type: "text" },
          { id: "tax", label: "LHDN income tax no.", type: "text" },
          { id: "children", label: "PCB / MTD: number of children claimed", type: "number" },
        ], note: "Employees Provident Fund Act 1991; Employees' Social Security Act 1969; Employment Insurance System Act 2017; Income Tax (Deduction from Remuneration) Rules 1994." },
        { id: "c", title: "C. Salary payment", fields: [
          { id: "bank", label: "Bank name", type: "text", req: true },
          { id: "acctname", label: "Account holder name", type: "text", req: true },
          { id: "acctno", label: "Account number", type: "text", req: true },
          { id: "branch", label: "Branch", type: "text" },
        ], note: "Wages are paid into a bank account in the employee's name (Employment Act 1955, section 25)." },
        { id: "d", title: "D. Emergency contact", fields: [
          { id: "ec_name", label: "Name", type: "text", req: true },
          { id: "ec_rel", label: "Relationship", type: "text", req: true },
          { id: "ec_tel", label: "Mobile telephone", type: "tel", req: true },
          { id: "ec_alt", label: "Alternative telephone", type: "tel" },
        ] },
        { id: "e", title: "E. Declaration", fields: [
          { id: "decl", type: "consent", req: true, wide: true, label: "I confirm that the particulars above are correct and will notify HR in writing of any change. I authorise the Company to register me with, and remit statutory contributions to, the Employees Provident Fund, the Social Security Organisation, the Employment Insurance System and the Inland Revenue Board, and to make the deductions required by law from my wages." },
          { id: "sign", type: "sign", req: true, wide: true, label: "Type your full name as your signature" },
        ] },
      ],
    },
  };

  // Which forms each invite stage presents, in order.
  const stages = {
    application: ["application", "pdpa"],
    offer: ["declaration"],
    onboarding: ["particulars"],
  };

  return { forms, stages, YN };
});
