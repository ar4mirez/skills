# Showing progress, deciding when to stop, moving on

Source: *Shape Up*, chapters 13–15 (https://basecamp.com/shapeup/3.4-chapter-13
through /3.6-chapter-15). This is a paraphrased working guide.

## Contents
- Why task counts and estimates mislead
- The hill: uphill vs. downhill, scopes on the hill
- Reading a hill chart (stuck dots, splitting scopes, backsliding)
- Sequencing: scariest first
- Deciding when to stop: baseline, scope hammering questions, QA, code review
- When to extend (the narrow exception)
- Moving on after shipping

## Why task counts and estimates mislead

- **Tasks that aren't there.** A list with no open items might be done, or its
  work might not be discovered yet. QA *adds* tasks, and lists grow as work
  progresses. At any given moment, an outsider can't tell whether the open
  count will go up or down.
- **Estimates hide uncertainty.** A routine four-hour task and a never-done-
  before four-hour task with unclear interdependencies aren't the same thing.
  "4 hours, or maybe 3 days" is meaningless.
- So shift from *done versus not done* to **unknown versus solved**.

## The hill

Every piece of work has two phases:
- **Uphill: figuring out what to do.** It's full of uncertainty and problem
  solving. "What percent complete?" makes no sense here.
- **Top of the hill: "now I know what to do."** You can see every remaining
  step, and estimating becomes fair.
- **Downhill: getting it done.** It's execution, with certainty.

The book's analogy is a dinner party. Choosing a cuisine is halfway up. Picking
the recipe and writing the shopping list is the top. Shopping, cooking, and
cleaning are downhill.

**Scopes on the hill:** each scope is a dot. The scope map gives the words
("Locate", "Reply"), and the hill gives the status (uphill or downhill). The
team, who hold the context, drag the dots themselves. That gives **status
without asking**, so managers don't have to interrupt.

**The killer feature is history.** Comparing snapshots shows *movement*: what's
in motion, what's stuck, which problems the team chose to solve, and how long
each spent at each stage.

### Encoding for `scripts/hill_chart.py`

Positions run from **0 to 100**:
- 0 is not started;
- 1–49 is uphill;
- 50 is the top;
- 51–99 is downhill;
- 100 is done.

A snapshot is JSON: `{"project", "date", "cycle_week", "scopes": [{"name",
"position", "note"}]}`. See `assets/hill-snapshot.json`.

## Reading a hill chart

- **Nobody says "I don't know."** People hide uncertainty, and risk
  accumulates. A **dot that doesn't move is a raised hand**, so respond to it
  early. Keep the conversation about the work, not the person: "What can we
  solve to get *Autosave* over the hill?" Then offer senior help or rework the
  concept.
- **A stuck dot may be a badly drawn scope.** In the book, "Notify" sat still
  for six days because it was really three things: the email design (near the
  top), delivery (almost done), and the in-app menu (not started). Split it
  into scopes that can move independently, and progress shows more often.
- **Backsliding** (a dot placed at or over the top that later has to be dragged
  back uphill, so its position number goes down) usually means someone did the uphill work in their head instead
  of with their hands ("I'll just use that API"). Coach this progression:
  - the first third up is "I've thought about this";
  - the second third is "I've validated my approach";
  - the top is "I've built enough that I don't believe there are other
    unknowns."

## Sequencing: solve the scariest first

- Ask: "If we ran out of time, which of these could we whip together anyway,
  and which could blow up?" Push **the riskiest, most novel scopes uphill
  first**, such as geocoding the team has never done. Leave routine ones for
  last, such as an email template that can be done in a day in the final week.
- Work expands to fill the time available, so routine work done first eats the
  cycle.
- Follow the **inverted pyramid** that journalists use: essentials first, so the
  end can be cut without losing anything essential.
- Near the end, what's left should be nice-to-haves and maybes, not unknowns.

## Deciding when to stop

### Compare down to baseline, not up to ideal

Pride in the work matters, but aim it at the right target. Ask: how do
customers solve this today, and what's the frustrating workaround? If the work
is clearly better than that baseline, it's good enough to ship. The contrast is
"never good enough" versus "better than what they have now."

### Limits motivate trade-offs

The circuit breaker makes every "wouldn't it be better if..." answer to "is
there time for this?" The team creates its own work, so question new work
before accepting it.

### Scope grows like grass

Scope creep isn't anyone's fault. Projects are opaque at the macro level until
you dig in. Don't try to stop scope from growing. Give the team the tools,
authority, and responsibility to cut it constantly. **Cutting scope isn't
lowering quality.** Choosing what's core and what's peripheral differentiates
the product. Stay picky about the quality of what ships.

### Scope-hammering questions

Ask these of every new fix, addition, or improvement:
- Is this a must-have for the new feature?
- Could we ship without this?
- What happens if we don't do this?
- Is this a new problem, or a pre-existing one customers already live with?
- How likely is this case or condition to occur?
- When it occurs, which customers see it? Is it core or an edge case?
- What's the actual impact if it happens?
- When it doesn't work well for a use case, how aligned is that use case with
  our intended audience?

Must-haves go on the scope as tasks, and the scope isn't done until they are.
Nice-to-haves get a `~` and are cut if time runs out, which it usually does.

### QA is for the edges

- Designers and programmers own basic quality, and programmers write their own
  tests. QA comes in near the end to hunt edge cases. It's a **level-up, not a
  gate**. Basecamp had no QA role for years and added one only when edge cases
  started to hit thousands of users.
- Every QA finding starts as a nice-to-have. The team triages it. The rigorous
  version is to collect QA issues on a separate list and move the must-haves
  into the scope they affect, so it's clear that scope isn't done yet.
- **Code review works the same way.** It's valuable, especially as teaching,
  but it's not a mandatory checkpoint.

## When to extend (rare)

Extend, typically by up to about two weeks and often absorbed by cool-down,
**only if both** of these are true:
1. The outstanding tasks are **true must-haves** that survived every attempt
   to hammer them.
2. The outstanding work is **all downhill**, with no unsolved problems or open
   questions.

If any work is still uphill at the deadline, there's a hole in the shaping.
Don't extend. Bet on something else next cycle, and put this project back on
the shaping track. Even when both conditions hold, prefer to enforce the
appetite. Running into cool-down regularly points to a shaping problem or a
team performance problem.

Use this format when advising at the deadline:

```
Recommendation: SHIP | SHIP WITH CUTS | EXTEND ≤2 WEEKS | STOP AND RESHAPE
Remaining work: <scopes and their hill positions>
Must-haves left (all downhill?): <yes/no + list>
Cuts (~): <list>
Reason: <one or two sentences tied to baseline and circuit breaker>
```

## Moving on after shipping

- **Let the storm pass.** Launches trigger requests, bug reports, and sometimes
  loud pushback ("You ruined it! Change it back!"). Wait a few days, stay firm,
  and remember why you made the change and who it helps.
- **Stay debt-free.** Committing to changes in response to feedback spends
  next cycle's clean slate. Say a gentle "no," and keep contemplating the idea.
- **Feedback needs to be shaped.** New requests are raw ideas that go back to
  step one, Set Boundaries. If one is truly urgent, make it the top priority on
  the *shaping* track next cycle. Meanwhile, bet the builders on something else.
