# Betting: cycles, the betting table, and product modes

Source: *Shape Up*, chapters 7–9 (https://basecamp.com/shapeup/2.1-chapter-07
through /2.3-chapter-09). This is a paraphrased working guide.

## Contents
- No backlogs; decentralized lists
- Cycles, cool-down, and team sizes
- The betting table and the meaning of a bet
- Uninterrupted time and the circuit breaker
- Bugs
- Keeping the slate clean; multi-cycle work
- Questions asked at the table
- Product modes: existing product, R&D, production, cleanup
- The kick-off message

## No backlogs

- Backlogs are dead weight. They grow forever, make everyone feel behind, and
  eat time in grooming and re-reading ideas that were only important a quarter
  ago.
- The betting table sees only **a few potential bets**: pitches shaped during
  the last six weeks, plus any older pitch that someone **deliberately revived
  and lobbies for**.
- A pitch that isn't bet on is **let go**. Nothing central gets tracked.
- **Decentralized lists** are fine. Support keeps its list of top issues,
  Product keeps ideas it hopes to shape, and programmers keep bugs they'd like
  to fix. None of these feed the table directly. Occasional one-on-ones
  between departments cross-pollinate ideas, so anything that comes back
  arrives *with context, a person, and a purpose*.
- Ideas are cheap. Important ideas come back, and recurring pain resurfaces on
  its own.

When a user asks you to "organize the backlog", don't groom it. Help them pick
the two or three items worth *shaping* now. Tell them the rest can live in
people's own lists or be dropped, and that important items will come back.

## Cycles and cool-down

- **Six weeks** is long enough to build something meaningful end to end, and
  short enough that the deadline is felt from day one. Two-week sprints are too
  short to finish meaningful work, and planning them costs more than they
  deliver.
- **Cool-down** is two weeks after each cycle with no scheduled work. Builders
  fix bugs, explore ideas, and try technical experiments. The betting table
  meets during cool-down, because the end of a cycle is the worst time to plan.
- **Teams:** one designer plus one or two programmers, with a QA person joining
  late in the cycle.
  - **Big batch team:** one project for the full cycle.
  - **Small batch team:** several 1–2-week projects. The team decides how to
    juggle them, and all must ship by the end of the cycle.

## The betting table

- **Who:** the few people with final authority. At Basecamp that's the CEO
  (the last word on product), the CTO, a senior programmer, and the product
  strategist. There's no "step two" approval afterward, and nobody can
  override the plan mid-cycle.
- **Format:** short (an hour or two) and infrequent. Pitches are read
  beforehand. Context gets built in ad-hoc one-on-ones during the preceding
  weeks.
- **Output:** a **cycle plan**, meaning which pitches, which team, and which
  people. See `assets/betting-table-template.md`.

### The meaning of a bet

1. **Bets have a payout.** The work was shaped so there's something meaningful
   finished at the end, rather than a time box filled with tasks.
2. **Bets are commitments.** The team gets the whole cycle, exclusively.
3. **Bets cap the downside.** At most, you lose one cycle.

### Uninterrupted time

Honor the bet. "Just a few hours" or "just one day" isn't cheap, because
momentum is a curve, not a point. Losing the wrong hour can kill a day, and
losing a day can kill a week. A new issue waits at most one cycle, which is why
you bet only one cycle ahead. True crises are the only exception, and they're
rare.

### The circuit breaker

- By default, **there's no extension**. If the work doesn't ship within the
  bet, the project as pitched doesn't happen.
- This eliminates runaway projects, since something worth six weeks isn't
  worth eighteen.
- It signals a **shaping** failure. Reframe the problem on the shaping track,
  and re-pitch only if the new approach really changes the odds.
- It pushes teams to own their trade-offs throughout the cycle.
- For the narrow exceptions, see `progress-and-stopping.md` > When to extend.

## Bugs

A bug isn't automatically more important than anything else. Drop everything
only for a **real crisis**: data loss, the app grinding to a halt, or a huge
number of customers seeing the wrong thing. Otherwise, choose one of these:
1. **Cool-down.** Two weeks out of every eight adds up to a lot of fixing time.
2. **Betting table.** Shape the fix into a pitch and let it compete. For
   example: "Move this slow synchronous step to a background job."
3. **Bug smash.** Dedicate a whole cycle, about once a year (Basecamp does it
   around the holidays), to bugs. The team self-organizes it.

## Keep the slate clean

- Bet **one cycle at a time**. Never carry scraps over without re-shaping them
  as a new bet.
- A longer-range roadmap can live "in your head and side-channel discussions",
  not as commitments.
- **Multi-cycle features:** shape a specific six-week target that ends with
  something fully built and working. Then decide on the next cycle fresh. You
  can continue, redefine, or pause for something urgent.

## Questions asked at the table

Use these to run or simulate a betting table.

- **Does the problem matter?** Weigh it against other problems. Different roles
  weigh differently: a small segment might carry a big support burden. A
  sweeping solution may mean the problem isn't narrowed yet. Look for the 20%
  of the change that delivers 80% of the benefit.
- **Is the appetite right?** If someone balks, one of four things usually
  happens:
  - the shaper adds context that swings opinion;
  - asking "how would you feel about two weeks?" uncovers the real objection,
    for example "I don't want another dependency there";
  - the shaper drops it;
  - the shaper reshapes it smaller or does more research.
- **Is the solution attractive?** Screen real estate and other scarce design
  resources have a cost. Are we "selling" them too cheaply? Don't do design
  work at the table. "We're not doing design here" pulls the conversation back
  up.
- **Is this the right time?** Think about recent work mix, morale (the same
  area of the app again?), and whether it's been a while since there was a
  newsworthy launch or since long-standing requests were fixed.
- **Are the right people available?** Match expertise to the project,
  including someone strong with the scope hammer for creep-prone work. Rotate
  big and small batch work. Check vacations and sabbaticals ("Calendar
  Tetris"). Some companies let people choose projects, which can work and adds
  buy-in.

## Product modes

"Look where you are" in the product's arc before betting.

| Mode | When | Shaping | Team | Expectation |
|---|---|---|---|---|
| **Existing product** | Adding to a product customers use | Standard, well-shaped pitch | Any cycle team | Ship to customers at cycle end |
| **R&D** | A brand-new product; the core is only a theory | Fuzzy; bet time on *spiking* key pieces | Senior people only (e.g. CEO/designer plus CTO) | Learn and commit load-bearing structure. **Don't expect to ship** |
| **Production** | Core architecture settled | Deliberate again | Other teams can join; parallel bets | "Ship" means merge to main and not touch it again. Features can still be cut before launch |
| **Cleanup** | Final stretch before launch | **None**. A free-for-all, like a bug smash | No team boundaries; leadership steers | Ship continuously in small bites. **At most two cycles.** Make the final-cut decisions here |

Still bet one cycle at a time in every mode. HEY spent about a year in R&D,
about a year in production, then two cleanup cycles, and cut its feature set to
launch. The betting table never committed to "two years of HEY" up front.
Experimental features on an existing product (for example, Hill Charts) can be
framed like production-mode bets: build a version good enough for internal use
first, and decide on a second cycle only afterward.

## The kick-off message

After betting, someone from the table announces the bets company-wide. The
announcement names each project, with a short paragraph and the team. Each
project then starts with the pitch, or a distilled version of it, posted to the
project space, followed by a kick-off call for questions. See
`assets/kickoff-message-template.md`.
