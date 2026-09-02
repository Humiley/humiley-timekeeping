# Running the design-control module on a real commission

Eleven rules went into this module in a fortnight. Every one was verified against tests, and none
against an engineer trying to issue a drawing at five on a Friday. This is how to close that gap
before adding anything else.

The risk is specific. A control that stops the wrong thing does not get reported and fixed — it
gets **routed around**. People stop recording the gate, leave the hold out of the register, mark
everything commission-wide. The register then looks populated while meaning nothing, which is worse
than the state before it existed, because now it is trusted.

The pilot exists to find that out cheaply, on one job, while it is still easy to change.

---

## Before day one

**Choose a commission that will actually issue something externally** within the fortnight. Almost
every rule fires at external issue — the independent check, open holds, unagreed deviations,
uninformed residual risks. A commission that never reaches IFA/IFC exercises none of them and will
tell you the module does nothing.

**Set four things, or most rules stay silent:**

| Set on the commission | If you don't |
|---|---|
| Deliverable **weight unit** (manhours vs points) | CPI reads *"Not measured"* for ever — deliberately, it will not divide points by hours |
| At least one **adopted code** | gate readiness reports "no code adopted at all" |
| **Design Manager** and **Lead Engineer** | nobody can sign a gate, adopt an edition, or close a hold |
| **Document numbering format** | the register check flags every drawing as off-format |

**Take a baseline.** Overview → *Schedule baseline* → **Take baseline**. Without one, SPI is
measured against the *current* planned dates — the same field somebody edits when a drawing slips —
so moving a date puts the index back to 1.00 and nothing records that the plan moved. One is taken
automatically at the next signed gate, but a commission already in Detailed Design will not reach a
gate inside the fortnight.

**Name one person who owns the registers.** Not a committee. Registers without an owner fill with
blanks and "commission-wide", and every later question about the data becomes unanswerable.

---

## Read this if you saw the module before 2 September 2026

The brief above was written against a version of this module that did not work the way it described,
and anyone who tried it then formed a fair impression from a broken screen.

**Eight of the twenty-one tabs painted nothing.** The dispatcher discarded what those renderers
returned, so the panel kept the *previous* tab's content — which is worse than a blank one, because
another register's table under a new heading reads as this register's data. Four of the eight are
registers this pilot is about to measure: **Holds & Assumptions, Deviations, Design Risk and
Register Check**. If somebody looked at Holds a fortnight ago and saw a list of drawings, that is
why.

**The competence register had no screen at all** — rules, tests and refusal-log integration, and
nowhere to enter a row. There is now a **Competence** tab under Planning, and a panel showing
checks already signed that the register does not cover.

**The schedule had no baseline.** See above; it does now.

**The tabs are grouped.** Twenty-two registers now sit under six process pills — Planning,
Requirements, Production, Verification, Issue & response, Change & control — rather than one flat
row of twenty-one.

None of this changes what the pilot is for. It changes whether a quiet log means what it looks like:
*"nobody used the Holds register"* would have read as disinterest and actually been a blank screen.

---

## Tell the team the exits exist

Every rule has a way through. A rule people cannot get past is experienced as breakage, and that is
how a module gets switched off in week one.

| Situation | The way through |
|---|---|
| Gate blocked by open holds or unagreed deviations | **Passed with actions** — records what is carried forward |
| Change is out of scope but we are not billing it | **No — at our cost**, so the decision to absorb is on the record |
| Drawing not ready for the client | **IFR** — internal issue is never blocked by anything |
| Client never answered and the transmittal must close | **Closure note** — say what happened |
| A signed record is wrong or superseded | **Supersede** or **void** — never delete |

That last row matters most. Deleting a signed record is refused outright, and people reach for
delete when they mean supersede.

---

## Change nothing for two weeks

Resist tuning. The log is only worth reading if it records what happened, not what happened to a
rule that was adjusted on day three. Write down complaints as they come; do not act on them yet.

---

## Then read the log

Open the commission and go to **Change & control → Refusal Log**. It is offered to the Design
Manager, the Lead Engineer and the QA approver named on the commission, and to portal managers —
the same people the server lets read it. Everyone else does not see the tab, and would get nothing
if they called the API directly.

The top table is the one to start on: **every rule that fired, most-fired first**, with how many
times, how many different people, and how many different records. Those three columns are not the
same number and the difference is the point — one engineer retrying one drawing four times is
somebody stuck, not a rule firing across the office. **Export CSV** takes the fortnight away with
you.

Three outcomes, three different meanings:

**Refused → record fixed → action completed.** The rule worked. Leave it alone.

**Refused → escape hatch used.** Also fine; that is what the exits are for. But if one rule is
escaped *every single time*, it is set at the wrong threshold or fires at the wrong moment.

**Refused → nothing happened afterwards.** The action was abandoned. This is the one to
investigate, and it needs a conversation rather than a code change: was the rule wrong, was the
timing wrong, or was the message unclear?

**Also watch what does not appear.** A rule with zero refusals either protects something genuinely
rare, or people have learned to avoid the path entirely. Those look identical in the data and only
a person can tell them apart.

**One prediction, written down before the fortnight so it can be wrong.** The gate's exit checks are
scoped to the whole commission, not to the stage being passed — an open HOLD raised during
Feasibility still blocks a clean pass at Detail. On a commission with any history that may make
*Passed with actions* the only reachable outcome, every time. If the log shows that rule escaped on
every gate, it is set at the wrong moment and the fix is earned. If it does not, this prediction was
wrong and the rule stays as it is. Deciding now, without the fortnight, would be guessing either way.

Rows with `source: advisory` are not refusals. Today that is the competence check — a drawing
checked by somebody authorised for a different discipline. Those are gaps in the register rather
than blocked work, and they tell you whether the competence records reflect reality yet.

---

## What to bring back

- The `eng_refusals` rows for the fortnight.
- Which refusals people **argued about** — that is not in the data and it is the most useful part.
- Whether the four setup fields stayed accurate, or drifted the moment somebody was busy.
- **Which tabs nobody opened.** Twenty-two registers is more than any one commission needs, and
  nothing in the data says which ones earned their place. An empty register is not automatically
  waste — some exist for the job that goes wrong — but a list of the ones nobody looked at is the
  only evidence that can say whether the twenty-third is worth building. It costs nothing to
  collect and it is worth as much as the log.
- **How many times the plan was re-cut**, and why. The Overview names the count; the reasons are on
  each baseline. A programme re-baselined three times in a fortnight is telling you something about
  the estimate, not about the engineers.

That is enough to tune the rules on evidence. It is worth more than the next three features,
because it is the only thing that can tell you whether the first eleven were right.

---

## What is deliberately not built yet

**Any judgement about what a refusal MEANT.** The Refusal Log screen exists now — it had to, or
the fortnight would have ended with the evidence collected and unreadable — but it deliberately
stops at what the data supports: the rule, the record, the person, the message. It has no outcome
column, because the three outcomes above are not something a refusal knows about itself. Which of
the three happened comes from asking the person, and that is the half of the pilot no screen can
do for you.

The screen will want a second pass after the pilot, against real rows rather than imagined ones.
Note what you wanted to see and could not.

**The client comment view.** It is the only proposed feature that fails in the dangerous direction:
every rule here fails safe, but an access boundary that leaks shows one client another client's
drawings and nobody reports it. The boundary it would depend on is measured and recorded in
`tests/test_eng_commission_boundary.py` — **a staff account currently sees every commission's
deliverables**, which is fine inside one office and unusable as the basis for client access. Any
client view must filter server-side by commission itself, on the list *and* the single-record
endpoint, and be tested on its own filter.
