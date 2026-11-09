# KEvidence — 10-minute demo for EFSA scientific management

Audience: GMO, pesticides, feed additives, enzymes, toxicology experts. Sceptical of AI.
Thesis: **AI is not a chatbot. It is the fourth generation of computing, and it lets anyone build the tool they need. KEvidence is the proof.**

Rule for the whole talk: show, don't tell. Every claim below is something on screen.

---

## Files you need

All are in the repository. Download them to the demo laptop's desktop before the meeting.

| File | Used in | What it is |
|---|---|---|
| `static/samples/characterisation_demo_dossier.md` | Act 2 | Fictional, deliberately incomplete feed-additive dossier (vanillin, "DemoVan 99"). |
| `static/samples/sanitisation_demo_study_report.pdf` | Act 3 | Fictional 3-page GLP tolerance study in chickens, with names, e-mail, phone, signature and confidential business info. |
| `data/guidance/feed/efsa_2017_5023.pdf` | backup | FEEDAP 2017 characterisation guidance (also served by the app). Open on p.5–6 if someone challenges a quote. |

Never use a real dossier in the demo. Both samples are fictional and say so on page 1.

---

## Runbook — the day before

1. Sign in on the demo URL with your email. Do it on the demo laptop, so the 14-day session is live tomorrow. No sign-in on stage.
2. **AI configuration**: add a provider and key (Mistral AI = EU-hosted, best story for this room). Click *Test connection*. You will not need it for the main demo; it is a backup.
3. Dry-run Acts 2 and 3 twice, full screen, with a timer.
4. Browser: zoom 125 %, close other tabs, notifications off, bookmarks bar hidden.
5. Second tab: the GitHub repository page (commit history, pull requests).
6. Offline fallback: run it locally (`KEVIDENCE_HOME=$PWD python server.py`, http://127.0.0.1:3457). Everything except the AI assistant works without internet.

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

### Act 2 — The workflow (1:30 – 2:30)

**Point at the left pane.**

> "It follows a mandate the way you run one. Mandate and problem formulation. Dossier evaluation. The four Codex steps — hazard identification, hazard characterisation, exposure, risk characterisation. Uncertainty. The opinion. Publication."

**Click through the twelve domain cards in Mandate & question.**

> "Twelve EFSA areas: feed, food additives, enzymes, FCM, novel foods, GMOs, pesticides, contaminants, biohazards, NAMs. All get the workflow and publication. One — feed additives — is *grounded*: the tool checks a dossier against the guidance itself. That's what I'll show. I'll come back to your area at the end."

### Act 3 — Characterising a dossier (2:30 – 5:30)

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

### Act 4 — Publication under the Transparency Regulation (5:30 – 7:30)

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

### Act 5 — Why you can trust what it shows (7:30 – 8:30)

**Back to Identity & characterisation → open *About the guidance grounding* (shows e.g. "29/29 entries anchored verbatim" per source).**

> "166 requirements from ten guidance documents — FEEDAP characterisation, consumer safety, target species, environment, microorganisms, renewal, QPS, WGS, VICH — each quoted word for word with its page. The PDFs are bundled, unmodified. At start-up every quote is re-anchored against the PDF text, and 130 automated tests fail if a single quote or page number drifts. It's grounded, not generative."

Optional, only if time and the AI is configured: in Publication, ask the Evidence Assistant something outside the rules (e.g. "What is the ADI of vanillin?"). It refuses and says why.

### Act 6 — Limits, and the point (8:30 – 10:00)

> "Where it stops — read this before anyone else says it:
> - It locates evidence; it does not judge adequacy. 'Not located' can be an extraction limit, not a gap.
> - Scanned PDFs need OCR. Text inside images isn't read.
> - Only feed additives are grounded today, chemical characterisation only — production strains are out of scope.
> - The hazard, exposure and risk-characterisation steps are structured scaffolding — AOP-Wiki, OpenFoodTox, NAM screening margins — not validated thresholds.
> - It runs locally. AI is off by default, uses *your* provider, and sends nothing unless you tick it per run.
>
> Now the point. **Switch to the GitHub tab, show the commit history.** I started this in June. Sixty-nine commits. Every feature you saw went from idea to working, tested software in hours, not procurement cycles. Release cycles went from months to minutes.
>
> Adding your area — pesticides, GMOs, enzymes — needs no code: a folder with your guidance PDFs and a list of requirements quoted from them. You know the guidance. I don't. That's the division of labour: you bring the judgment, the machine brings the computing.
>
> It's open source, AGPL. Break it. Tell me where it's wrong."

---

## Likely questions — short answers

| Question | Answer |
|---|---|
| "Does our dossier go to OpenAI / the US?" | No. Extraction, gap analysis and sanitisation run on the server, no AI. AI is per user, off by default, ticked per run; Mistral (EU) or an on-premises model are options. |
| "It hallucinates." | The parts shown use no generation. Requirements are verbatim quotes checked by tests. When AI drafts, every number is checked against the dossier and untraced numbers are flagged. |
| "Who validated it?" | Nobody yet. It's a prototype. That's the ask: your experts reviewing the catalogues and rules. |
| "Can it do microbial / GMO / pesticide dossiers?" | Workflow and sanitisation yes (all Annex sectors a–h). Guidance grounding not yet; it's a data task, not a code task. |
| "Is it IUCLID-compatible?" | OpenFoodTox can be read from a local IUCLID 6 instance; dossier import from IUCLID is not built. |
| "Who maintains it?" | Open source; any administration can run and adapt it. Built with AI, maintainable with AI. |

## If something breaks on stage

- Upload hangs → refresh, rerun; it's under 2 seconds locally. Switch to the local fallback.
- Signed out → this is why you sign in the day before; the console fallback prints the link.
- Assistant errors → skip it; nothing in the core demo depends on AI. Say so: it proves the point.
