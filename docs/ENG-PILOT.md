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

**Name one person who owns the registers.** Not a committee. Registers without an owner fill with
blanks and "commission-wide", and every later question about the data becomes unanswerable.

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

Rows with `source: advisory` are not refusals. Today that is the competence check — a drawing
checked by somebody authorised for a different discipline. Those are gaps in the register rather
than blocked work, and they tell you whether the competence records reflect reality yet.

---

## What to bring back

- The `eng_refusals` rows for the fortnight.
- Which refusals people **argued about** — that is not in the data and it is the most useful part.
- Whether the four setup fields stayed accurate, or drifted the moment somebody was busy.

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
