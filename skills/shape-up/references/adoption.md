# Adopting and adapting Shape Up

Source: *Shape Up*, appendices "Adjust to Your Size" and "How to Begin to
Shape Up" (https://basecamp.com/shapeup/4.1-appendix-02,
/4.2-appendix-03), plus the Basecamp implementation appendix (/4.0-appendix-01).
The sections **Mapping to other tools** and **Working with AI coding agents**
are this skill's own adaptations, not from the book. Label them that way when
you use them.

## Basic truths vs. specific practices

Separate what's universal from what depends on scale:

- **Basic truths**, which hold for every team size:
  - Work has to be *shaped* before it's done, whether for another team or for
    your future self. If you don't make trade-offs up front, deadlines and
    constraints will force them on you later in a mad rush.
  - Be deliberate about what you *bet* on, and cap the downside with a circuit
    breaker, whatever the time frame.
  - While *building*, separate knowns from unknowns, sequence the unknowns
    first, and reserve capacity for them.
- **Specific practices**, which depend on scale: six-week cycles, two-week
  cool-down, formal pitches, the betting table, dedicated shapers, hill charts,
  and a QA role.

## Small enough to wing it (about 2–3 people)

- Everyone wears every hat, so long uninterrupted blocks are hard to get, while
  communication is cheap.
- **Drop the structure.** Skip fixed cycles, cool-down, formal pitches, and the
  betting table. Alternate shaping and building with the same people.
- **Keep the phases.** Be explicit about which hat you're wearing. Set an
  appetite, shape the next thing, build it, then shape the next. Bets can vary
  in size (two weeks here, three weeks there).

## Big enough to specialize

- Once you grow, fluid chat-driven coordination becomes a liability, and things
  slip through the cracks.
- Adopt six-week cycles, cool-downs, and a formal betting table. Someone, such
  as a founder or a senior designer promoted out of in-cycle work, must spend
  real time shaping on the out-of-cycle track.
- Protect the builders with other functions. At Basecamp's size (about 50
  people, around a dozen in product), that meant:
  - a Security, Infrastructure, and Performance team for low-level structural
    work;
  - Ops to keep the lights on;
  - technical Support staff to investigate customer issues.

  None of them interrupt Core Product during cycles.

## How to begin

Pick one option. Recommend **A** by default, B when someone else controls
engineering time, and C when the pain is sprint overhead.

- **Option A: one six-week experiment.**
  1. Shape one significant project that fits *comfortably* in six weeks. Be
     conservative the first time.
  2. Carve out one designer and two programmers for the full six weeks, and
     guarantee they won't be interrupted.
  3. Skip the betting table and just plan to do the shaped work.
  4. Kick off with a full pitch, and set the expectation that the team
     discovers and tracks its own tasks.
  5. Give the team a dedicated room or chat channel.
  6. Push them to get one piece done by wiring UI and code together early.

  Skip scope mapping and hill charts at first. Introduce them once the team is
  comfortable getting one piece done, because it's the same idea repeated.
  Then use the result to lobby for wider change.
- **Option B: start with shaping.** When a CTO or someone else controls
  programmers' time, shape one compelling project with clearer boundaries than
  usual and put it through the existing process, "even if it's a paper
  shredder." Better-shaped work builds the case for longer cycles and
  deliberate betting.
- **Option C: start with cycles.** Replace two-week sprints with six-week
  cycles to cut planning overhead and build momentum. Shaping follows
  naturally once people have room to breathe.

Two principles apply to every option:
- **Fix shipping first.** Build the shipping muscle before investing in
  discovery or research. Insight you can't ship doesn't matter.
- **Focus on the end result.** Worries like "what if someone sits idle?" are
  micro-scale. Ask instead: will we feel good if this ships after six weeks?

## The Basecamp implementation, as a reference pattern

- **Shaping lives in a small private team space** ("Product Strategy") for
  shapers, trusted reviewers, and the betting table. Pitches are posted as
  messages in a "Pitch" category, and the betting table meets over video.
- **Bets are announced company-wide.**
- **Each cycle project gets its own project space**, named with the cycle
  ("Cycle 4: Autopay"). It includes the designer and programmers, with the
  pitch posted first.
- **Scopes are to-do lists, and tasks are to-do items.** A list's description
  summarizes its scope.
- **Hill charts** track each scope list as a dot. The team drags the dots and
  annotates updates, and the history view shows movement.

## Mapping to other tools (adaptation, not from the book)

The method is tool-agnostic. Keep the *semantics*, not Basecamp's UI. The
table below suggests mappings.

| Concept | GitHub | Linear | Jira | Notion / docs |
|---|---|---|---|---|
| Shaping space (private) | Private repo or discussions category | Private team/project | Restricted project | Private page tree |
| Pitch | Discussion or `pitches/<slug>.md` PR | Project doc | Confluence page linked to an epic | Page from `assets/pitch-template.md` |
| Cycle | Milestone "Cycle N" (6 wks) | Cycle (set to 6 weeks, with cool-down gaps) | Sprint or fix version spanning 6 weeks | Database property |
| Cycle project | Project board per bet | Project | Epic | Page per bet |
| Scope | Label `scope:<name>` or tracking issue with task list | Sub-project or milestone within the project | Story acting as a container | Toggle list per scope |
| Task | Issue or checklist item (created by the team) | Issue | Sub-task | To-do |
| Nice-to-have | Prefix `~` in the title, or label `nice-to-have` | Prefix `~`, or "Nice to have" label | Prefix `~` | `~` prefix |
| Hill chart | `scripts/hill_chart.py` snapshot committed weekly | Project update with hill SVG attached | Status page with SVG | Embedded SVG |

Pitfalls to warn about:
- **Tools with a backlog view.** Don't let a "Backlog" state become one.
  Archive un-bet pitches instead.
- **Velocity and burndown charts.** Turn them off or ignore them, since they
  measure task counts, not uncertainty.
- **Sprint rituals.** Don't import them into the cycle: no daily stand-up, no
  sprint planning.

## Working with AI coding agents (adaptation, not from the book)

The method's core idea is to shape before committing, give the builder a
bounded whole, integrate early, and track unknowns. It transfers well to
humans building with coding agents, or to agents acting as builders.

- **The pitch is the agent's brief.** An agent handed a raw idea ("add a
  calendar") will build the six-month version, or the wrong tenth of it. Hand
  it a pitch with elements, rabbit-hole patches, and explicit **no-gos**. No-gos
  matter even more for agents, because agents rarely cut scope on their own.
- **The appetite is still a budget.** State it in calendar time and in effort
  terms (sessions, review hours, token or cost budget). Apply the circuit
  breaker. If the budget runs out with uphill work left, stop and reshape.
  Don't keep prompting.
- **Projects, not micro-tasks.** Give the agent the whole shaped project and
  ask it to propose the **first piece** (core, small, novel) and to integrate
  end to end before breadth. Micro-tasked agents produce horizontal layers that
  don't connect.
- **Scopes are the checkpoints.** Ask the agent to maintain a scope map (see
  `assets/scope-map-template.md`) as it discovers work, with `~` for
  nice-to-haves, and to report status as hill positions per scope rather than
  "80% done."
- **Humans own the shaping and the betting.** The appetite, the problem story,
  and the no-gos are strategic calls. Agents can help explore elements,
  breadboard alternatives, and hunt rabbit holes ("is this possible within the
  appetite, in *this* codebase?"). The shaper decides.
- **Keep the builder's time uninterrupted.** Don't inject unrelated requests
  into an agent's cycle work. Route them to raw-idea intake instead.
- **Faster building doesn't remove the need to shape.** It moves the
  bottleneck to deciding what's worth building and where to stop. Shorter
  appetites, like one-week small batches, may become normal. Keep the rule
  that appetite comes before design.
