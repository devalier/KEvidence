# KEvidence — 10-minute demo for EFSA scientific management

Audience: GMO, pesticides, feed additives, enzymes, toxicology experts. Sceptical of AI.
Thesis: **AI is not a chatbot. It is the fourth generation of computing, and it lets anyone build the tool they need. KEvidence is the proof.**

Rule for the whole talk: show, don't tell. Every claim below is something on screen.

---

## Files you need

All are in the repository. Download them to the demo laptop's desktop before the meeting.

| File | Used in | What it is |
|---|---|---|
| `static/samples/characterisation_demo_dossier.md` | Act 3 | Fictional, deliberately incomplete feed-additive dossier (vanillin, "DemoVan 99"). |
| `static/samples/sanitisation_demo_study_report.pdf` | Act 4 | Fictional 3-page GLP tolerance study in chickens, with names, e-mail, phone, signature and confidential business info. |
| The two claim lines below, in a text file on the desktop | Act 4 | Confidentiality claims to paste, written in words (not verbatim from the PDF). |
| `data/guidance/feed/efsa_2017_5023.pdf` | backup | FEEDAP 2017 characterisation guidance (also served by the app). Open on p.5–6 if someone challenges a quote. |

Claims to paste in Act 4:

```
manufacturing process conditions | Art. 39(2)(a) GFL
identity of the guaiacol supplier | Art. 39(2)(b) GFL
```

Never use a real dossier in the demo. Both samples are fictional and say so on page 1.

---

## Runbook — the day before

1. Sign in on the demo URL with your email. Do it on the demo laptop, so the 14-day session is live tomorrow. No sign-in on stage.
2. **AI configuration — critical, Act 4 depends on it.** Add a provider and key. Mistral AI (EU-hosted) is the best story for this room; use a strong model (e.g. Mistral Large) — sanitisation needs judgment. Click *Test connection*. Once configured, *AI-led sanitisation* is pre-ticked in Publication.
3. Dry-run Acts 3 and 4 twice, full screen, with a timer. **Act 4 output comes from a live model and can vary.** Note what your model actually returns on the demo PDF (expected: 3 staff names, e-mail, phone masked; process and supplier masked as claimed; market share and composition shown but public) and adjust the Act 4 lines to match. If the model misses something, that's fine to show — the reviewer toggles it; say so.
4. Browser: zoom 125 %, close other tabs, notifications off, bookmarks bar hidden.
5. Second tab: the GitHub repository page (commit history, pull requests).
6. Offline fallback: run it locally (`KEVIDENCE_HOME=$PWD python server.py`, http://127.0.0.1:3457). Without internet, sanitisation runs on the rule-based fallback (see *If something breaks*).

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

### Act 4 — AI-led sanitisation under the Transparency Regulation (5:30 – 7:30)

**Publication.** Point at the ticked *AI-led sanitisation (recommended)* box and the provider name next to it.

> "Every study we publish has to be sanitised: personal data and confidential information masked, under 178/2002 as amended by the Transparency Regulation, following EFSA's own practical arrangements. Rules written as patterns fail here — names, claims and business information don't come in predictable formats. So here the AI does the work, on our provider, under EFSA's rules."

**Upload `sanitisation_demo_study_report.pdf`, applicant `Demo Feed Additives S.A.`, paste the two claim lines → *Propose redactions*.**

> "Two confidentiality claims, written in words, the way an applicant writes them. Not a single word of them appears in the document."

**Show the summary badge *AI-led sanitisation* and the counts by type, then the page preview.**

> "Two types of redaction, two sets of rules.
>
> Personal data — always masked. Study Director, pathologist, QA manager under Article 39e(2), testing personnel. E-mail, phone, signature under 39e(1).
>
> Confidential information — masked only when claimed. The AI found the passages the two claims describe: the process conditions and the exclusive supplier — masked, each tied to its claim, R1 and R2. The market share is an Annex item too, but nobody claimed it: shown, stays public. The quantitative composition: flagged as relevant to the safety assessment — never masked, even if claimed.
>
> What it left alone: the applicant's name and address — public by law — and the authors in the reference list."

**Point at the *AI-led* line (accepted / rejected counts).**

> "And the AI is not trusted blindly. Every finding must cite a rule that applies to this sector and be found word for word on its page, or KEvidence rejects it. The masking outcome is enforced by the code, not by the model. The old pattern rules still run underneath as a cross-check; anything only they found is flagged."

**Click *Generate sanitised PDF*. Show the verification report; click *Download sanitised PDF*, try to select text under a box.**

> "Real redaction, not a black rectangle over text you can copy out. It re-reads its own output: masked text gone, comments, links and metadata stripped. Verification passed.
>
> One caveat we print on screen: KEvidence recommends sanitisation be done by a sovereign, domain-specific model fine-tuned for this purpose — or a frontier model if your organisation permits it for this work. Without AI it falls back to rules, and says so. The decision on confidentiality stays with EFSA, Article 11."

### Act 5 — Why you can trust what it shows (7:30 – 8:30)

**Back to Identity & characterisation → open *About the guidance grounding* (shows e.g. "29/29 entries anchored verbatim" per source).**

> "166 requirements from ten guidance documents — FEEDAP characterisation, consumer safety, target species, environment, microorganisms, renewal, QPS, WGS, VICH — each quoted word for word with its page. The PDFs are bundled, unmodified. At start-up every quote is re-anchored against the PDF text, and over 170 automated tests fail if a single quote or page number drifts. It's grounded, not generative."

Optional, only if time and the AI is configured: in Publication, ask the Evidence Assistant something outside the rules (e.g. "What is the ADI of vanillin?"). It refuses and says why.

### Act 6 — Limits, and the point (8:30 – 10:00)

> "Where it stops — read this before anyone else says it:
> - It locates evidence; it does not judge adequacy. 'Not located' can be an extraction limit, not a gap.
> - Scanned PDFs need OCR. Text inside images isn't read.
> - Only feed additives are grounded today, chemical characterisation only — production strains are out of scope.
> - The hazard, exposure and risk-characterisation steps are structured scaffolding — AOP-Wiki, OpenFoodTox, NAM screening margins — not validated thresholds.
> - Extraction and gap analysis run locally, no AI. Where AI runs — sanitisation — it uses *your* organisation's provider, only when ticked, and every finding is checked against the rules and the page.
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
| "Does our dossier go to OpenAI / the US?" | Only to the provider *you* configure, and only for sanitisation when ticked. Extraction and gap analysis use no AI. Mistral (EU) or an on-premises model are options; the recommended end state is a sovereign model fine-tuned for sanitisation. |
| "It hallucinates." | Characterisation uses no generation. In sanitisation, a finding the AI invents is rejected: it must be found verbatim on its page and cite an applicable rule. What gets masked is decided by EFSA's rules in code: personal data yes; confidential information only if claimed and not safety-relevant. |
| "Why trust AI over rules for sanitisation?" | You don't trust either blindly: the AI finds, the rules constrain, the officer reviews every box. Rules alone can't link a claim written in words to the passage it means — you just saw the AI do it. |
| "Who validated it?" | Nobody yet. It's a prototype. That's the ask: your experts reviewing the catalogues and rules. |
| "Can it do microbial / GMO / pesticide dossiers?" | Workflow and sanitisation yes (all Annex sectors a–h). Guidance grounding not yet; it's a data task, not a code task. |
| "Is it IUCLID-compatible?" | OpenFoodTox can be read from a local IUCLID 6 instance; dossier import from IUCLID is not built. |
| "Who maintains it?" | Open source; any administration can run and adapt it. Built with AI, maintainable with AI. |

## If something breaks on stage

- Upload hangs → refresh, rerun; it's under 2 seconds locally. Switch to the local fallback.
- Signed out → this is why you sign in the day before; the console fallback prints the link.
- AI sanitisation fails or is slow (badge shows *Rule-based fallback*) → carry on: personal data is still proposed by the rules; the claims show as "not found verbatim" — say: "this is exactly why the AI leads; rules can't read a claim written in words." Then point at the recommendation box.
- Assistant errors → skip it.
