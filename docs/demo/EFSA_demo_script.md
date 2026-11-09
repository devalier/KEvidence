# KEvidence — 10-minute demo for EFSA scientific management

Audience: GMO, pesticides, feed additives, enzymes, toxicology experts. Sceptical of AI.
Thesis: **AI is not a chatbot. It is the fourth generation of computing, and it lets anyone build the tool they need. KEvidence is the proof.**

Rule for the whole talk: show, don't tell. Every claim below is something on screen.

---

## Files you need

All are in the repository. Download them to the demo laptop's desktop before the meeting.

| File | Used in | What it is |
|---|---|---|
| `static/samples/completeness_demo_dossier.zip` | Act 3 | Fictional, deliberately incomplete feed-additive application (15 files in the three-part folder structure). |
| `static/samples/characterisation_demo_dossier.md` | Act 4 | Fictional, deliberately incomplete feed-additive dossier (vanillin, "DemoVan 99"). |
| `static/samples/sanitisation_demo_study_report.pdf` | Act 5 | Fictional 3-page GLP tolerance study in chickens, with names, e-mail, phone, signature and confidential business info. |
| `docs/demo/Demo_Synthetic_Dossier.zip` | optional | Demo Synthetic Dossier: real-world-shaped food-enzyme use-extension package (14 PDFs in dossier folders), fictional applicant "Acme Enzymatic srl". For the enzyme variant of Act 3. |
| `data/guidance/feed/efsa_2017_5023.pdf` | backup | FEEDAP 2017 characterisation guidance (also served by the app). Open on p.5–6 if someone challenges a quote. |

Never use a real dossier in the demo. The samples are fictional or synthetic and say so (on page 1, or on every page for the Acme package).

---

## Runbook — the day before

1. Sign in on the demo URL with your email. Do it on the demo laptop, so the 14-day session is live tomorrow. No sign-in on stage.
2. **AI configuration**: add a provider and key (Mistral AI = EU-hosted, best story for this room). Click *Test connection*. You will not need it for the main demo; it is a backup.
3. Dry-run Acts 3 to 5 twice, full screen, with a timer.
4. Enzyme variant (optional): unzip `Demo_Synthetic_Dossier.zip` and **delete its `Documentation` folder** — those are helper files, not part of the dossier, and they contain the synthetic contact details, so the check would flag them too. Keep the remaining folders as they are.
5. Browser: zoom 125 %, close other tabs, notifications off, bookmarks bar hidden.
6. Second tab: the GitHub repository page (commit history, pull requests).
7. Offline fallback: run it locally (`KEVIDENCE_HOME=$PWD python server.py`, http://127.0.0.1:3457). Everything except the AI assistant works without internet.

## Runbook — 15 minutes before

- Open the app on **Mandate & question**, domain *Feed additives* selected.
- Files on the desktop.

---

## Script

Timings are cumulative. Spoken text in quotes. Actions in **bold**.

### Act 1 — The claim (0:00 – 1:30)

> "I'm not a scientist. I'm certainly not a risk assessor. Last spring I could not have told you what FEEDAP §2.1.4 requires.
>
> Most of you think of AI as a chatbot that sometimes invents things. That is the least interesting thing about it. AI is a new kind of computer. First generation: hardware wired by hand. Second: programs written by specialists. Third: packaged software — you wait for IT, a tender, a release next year. Fourth: you describe what you need and the tool exists by the afternoon.
>
> This is not about replacing your judgment. It is about replacing the third-generation software you work with today. I'll show you what one non-scientist built, and then I'll show you where it stops."

### Act 2 — The workflow (1:30 – 2:15)

**Point at the left pane.**

> "It follows a mandate the way you run one. Mandate and problem formulation. Intake — what the front desk does when a dossier arrives. Dossier evaluation. The four Codex steps — hazard identification, hazard characterisation, exposure, risk characterisation. Uncertainty. The opinion. Publication."

**Click through the twelve domain cards in Mandate & question.**

> "Twelve EFSA areas: feed, food additives, enzymes, FCM, novel foods, GMOs, pesticides, contaminants, biohazards, NAMs. All get the workflow and publication. One — feed additives — is *grounded*: the tool checks a dossier against the guidance itself. That's what I'll show. I'll come back to your area at the end."

### Act 3 — Intake: the completeness check (2:15 – 3:45)

**Intake → Completeness & sanitisation → upload `completeness_demo_dossier.zip`, applicant `Demo Feed Additives S.A.`, notified study IDs `STUDY-DEMO-0042, STUDY-DEMO-0099` → *Check completeness*.** (About a second, locally, no AI.)

> "Before anyone assesses anything, the front desk spends up to a month on this: is the dossier complete, are the studies notified, is the confidentiality request in order, is there personal data that must not be published. A fictional feed application, fifteen files, in the folder structure of our administrative guidance."

**Point at the red verdict: *Incomplete — 5 blocking, 5 warnings*. Scroll through the blocking items.**

> "No completeness checklist. No efficacy section. The public summary repeats a sentence from the confidential manufacturing process — it would have been published. A tolerance study that started in 2023 with no study ID: under Article 32b that puts validity at risk. And a study notified in our database that isn't in the dossier. Each line names the rule it comes from — our administrative guidance, our pre-submission arrangements — and the file and page it found."

**Point at one warning (*2.4 heading not located*, or the scanned annex). Then click *Download request for missing information*, open it for 3 seconds.**

> "Blocking items stop validation; warnings are worth raising — the same split IUCLID's validation assistant makes. And here is the draft letter to the applicant, numbered, with the 30-day deadline. A draft — the officer edits and signs."

**In the *Files* table, click *Sanitise* on `Annex_III_1_tolerance_study.pdf`.**

> "Personal data in a study report — one click and it's open in Publication, applicant pre-filled. I'll come back to publication."

**Click Identity & characterisation.**

### Act 4 — Characterising a dossier (3:45 – 6:00)

**Identity & characterisation → upload `characterisation_demo_dossier.md` → *Characterise from documents*.** (Runs in about a second, locally, no AI.)

> "A fictional vanillin dossier. Nothing typed in by me — it identified the additive, the form, the production route, the batches, each with document and page."

**Scroll to Table 1.**

> "This is §1.1.1 in the FEEDAP opinion layout: specifications, batch-to-batch as average, range and number of batches, impurities. Every value cites D1 p.1."

**Scroll to *Facts located for the scientific officer's conclusion*.**

> "Note the wording: *facts*, not conclusions. 3 of 3 batches meet the 99.5 % specification. But the guidance asks for five batches; it found three. It found a statement of compliance on impurities and flags it — the guidance says certificates with analytical values are required, p.5. No residual solvents located. And then a box: *Scientific officer to conclude.* It never writes your conclusion."

**Scroll to *Data-gap analysis*.** Read the counts: 3 not located, 7 partial, 6 applicability to confirm, 8 located.

> "Every one of the 29 requirements is quoted verbatim from the guidance, with section and page."

**Panel *Two questions that change which requirements apply*: tick *Via premixtures* + *In feedingstuffs*, choose *Flavouring compound* → *Run again*.**

> "It asks what it can't know. The guidance exempts flavouring compounds from stability in premixtures and homogeneity. Answer, rerun — 'applicability to confirm' drops from 6 to 2, 'not applicable' rises from 3 to 7. The guidance's logic, applied the same way every time."

**Click *Download Word (.docx)*, open it for 3 seconds.**

> "A draft section you can edit, marked as a draft for SO verification."

### Act 5 — Publication under the Transparency Regulation (6:00 – 7:45)

**Publication → upload `sanitisation_demo_study_report.pdf`, applicant `Demo Feed Additives S.A.` → *Propose redactions*.**

> "Every study we publish has to be sanitised under 178/2002 as amended by the Transparency Regulation, following our own practical arrangements."

**Show the page preview with boxes.**

> "Pre-selected: Study Director, pathologist, QA manager — Article 39e(2), testing personnel. E-mail, phone, the signature image — 39e(1). The lab's street address is proposed but *not* selected: personal or organisational? Your call.
>
> Page 2: manufacturing process, quantitative composition, the exclusive supplier, market share. Proposed under Article 39(2) — and *not* selected. They're masked only if confidentiality was requested and granted, never if relevant to safety.
>
> What it did *not* propose: the applicant's name and address — public by law — and the authors in the reference list."

**Click *Generate sanitised PDF*. Show the verification report; click *Download sanitised PDF*, try to select text under a box.**

> "Real redaction, not a black rectangle over text you can copy out. Then it re-reads its own output: masked text gone, comments, links and metadata stripped. Verification passed. The decision on confidentiality stays with EFSA, Article 11."

### Act 6 — Why you can trust what it shows (7:45 – 8:30)

**Back to Identity & characterisation → open *About the guidance grounding* (shows e.g. "29/29 entries anchored verbatim" per source).**

> "About 220 rules from thirteen EFSA and related documents — the ten behind characterisation (FEEDAP characterisation, consumer safety, target species, environment, microorganisms, renewal, QPS, WGS, VICH), our transparency arrangements, our pre-submission arrangements, and the administrative guidance with its completeness checklist — each quoted word for word with its page. The PDFs are bundled, unmodified. At start-up every quote is re-anchored against the PDF text, and about 200 automated tests fail if a single quote or page number drifts. It's grounded, not generative."

Optional, only if time and the AI is configured: in Publication, ask the Evidence Assistant something outside the rules (e.g. "What is the ADI of vanillin?"). It refuses and says why.

### Act 7 — Limits, and the point (8:30 – 10:00)

> "Where it stops — read this before anyone else says it:
> - It locates evidence; it does not judge adequacy. 'Not located' can be an extraction limit, not a gap.
> - Scanned PDFs need OCR. Text inside images isn't read.
> - Only feed additives are grounded today, chemical characterisation only — production strains are out of scope.
> - The intake checklists — feed additives and food enzymes — are grounded in public-consultation drafts (2018 administrative guidance; 2021 CEP scientific guidance); the current versions must be checked against them. Other areas get the generic intake checks only.
> - The hazard, exposure and risk-characterisation steps are structured scaffolding — AOP-Wiki, OpenFoodTox, NAM screening margins — not validated thresholds.
> - It runs locally. AI is off by default, uses *your* provider, and sends nothing unless you tick it per run.
>
> Now the point. **Switch to the GitHub tab, show the commit history.** I started this in June. Over seventy commits. Every feature you saw went from idea to working, tested software in hours, not procurement cycles. Release cycles went from months to minutes.
>
> Adding your area — pesticides, GMOs, enzymes — needs no code: a folder with your guidance PDFs and a list of requirements quoted from them. You know the guidance. I don't. That's the division of labour: you bring the judgment, the machine brings the computing.
>
> It's open source, AGPL. Break it. Tell me where it's wrong."

### Optional — the enzyme variant of Act 3 (if the room is enzyme-heavy, or in Q&A)

**Mandate & question → domain *Food enzymes*. Intake → type of application *Modification / extension of use (Part B)* → upload the unzipped dossier folder with the "dossier folder" button (`Documentation` removed beforehand), applicant `Acme Enzymatic srl` → *Check completeness*.**

> "A real-world-shaped enzyme package — an alpha-amylase use extension, fourteen PDFs in dossier folders, the applicant replaced by a fictional company. It's checked against our suitability checklist for food enzymes, Part B: reference to the existing authorisation, source unchanged, intended uses, exposure with FEIM — all located."

**Open *Applicant's checklist* (28 provided, 128 not relevant), then point at the warning *Copies of bibliographic references — declared vs found*.**

> "It reads the applicant's own ticks. They declared the copies of the references provided — each as a separate PDF. The package has a list of references, no copies. That's exactly what a suitability check catches."

**Point at the personal-data warning; click *Sanitise* on the cover letter: name, e-mail and phone pre-selected; the address is proposed but not selected.**

**Optional, 15 seconds: switch the type to *New food enzyme (Part A)* and rerun.**

> "Treated as a new enzyme, it lists what a full dossier would need and this one doesn't contain: whole genome sequence, strain deposit, flow chart, amino acid sequence, batch composition, toxicology. Correct — it's a use extension that relies on an earlier dossier."

Expect, as Part B: *Complete, with warnings* — the references declared-vs-found warning, personal data in the cover letter only, and the study-notification match marked *review* (no study IDs entered). As Part A: *Incomplete*, 6 blocking. The checklist rows quote the 2021 public-consultation draft of the CEP scientific guidance; say so if asked.

---

## Likely questions — short answers

| Question | Answer |
|---|---|
| "Does our dossier go to OpenAI / the US?" | No. Extraction, gap analysis and sanitisation run on the server, no AI. AI is per user, off by default, ticked per run; Mistral (EU) or an on-premises model are options. |
| "It hallucinates." | The parts shown use no generation. Requirements are verbatim quotes checked by tests. When AI drafts, every number is checked against the dossier and untraced numbers are flagged. |
| "Who validated it?" | Nobody yet. It's a prototype. That's the ask: your experts reviewing the catalogues and rules. |
| "Can it do microbial / GMO / pesticide dossiers?" | Workflow and sanitisation yes (all Annex sectors a–h). Intake checklists exist for feed additives and food enzymes; characterisation grounding only for feed additives. The rest is a data task, not a code task. |
| "Is it IUCLID-compatible?" | OpenFoodTox can be read from a local IUCLID 6 instance; dossier import from IUCLID is not built. |
| "Can it replace the front desk's completeness check?" | No. It does the mechanical part in seconds so staff spend their time on judgement: is a justification valid, is a study really in scope. It flags; EFSA or the Commission decides validity. |
| "How does it know a study had to be notified?" | It reads the study start date in the report: from 27 March 2021 it expects a study ID or a justification (pre-submission arrangements, Art. 19 and 21). Enter the IDs from the notification database and it also checks that every notified study is in the dossier (Art. 22(3)). |
| "Who maintains it?" | Open source; any administration can run and adapt it. Built with AI, maintainable with AI. |

## If something breaks on stage

- Upload hangs → refresh, rerun; it's under 2 seconds locally. Switch to the local fallback.
- Signed out → this is why you sign in the day before; the console fallback prints the link.
- Assistant errors → skip it; nothing in the core demo depends on AI. Say so: it proves the point.
