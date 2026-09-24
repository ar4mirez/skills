# Writing and reviewing pitches

Source: *Shape Up*, chapter 6 (https://basecamp.com/shapeup/1.5-chapter-06).
This is a paraphrased working guide. For the fill-in structure, use
`assets/pitch-template.md`.

## What a pitch is for

A pitch presents a **potential bet**. It captures the shaping work in a form
that people with less context can understand, so the betting table can make an
informed decision. It gets posted asynchronously, so stakeholders read it on
their own time and the betting meeting stays short. If the project is chosen,
the pitch is reused at kick-off.

Comments on a pitch are for **poking holes and adding missing information**,
such as technical constraints from the CTO. They are not a vote. Yes or no
happens at the betting table.

## The five ingredients (all required)

### 1. Problem
- Tell **one specific story** that shows why the status quo fails. That story
  becomes the **baseline** that every proposed solution is tested against.
- Always pair the problem with the solution. A solution without a problem gives
  no test of fitness, and the debate turns into UI preferences ("add tabs to
  the iPad app").
- Keep the problem separate so the table can debate **demand** on its own. Is
  this a problem for customers we want, or only for a poor-fit segment?
- How much context to include depends on how much the readers already share.

### 2. Appetite
- Name the time budget and the team size. "Six weeks, one designer and two
  programmers" (big batch), or "Looking for a 1-weeker" (small batch).
- Treat the appetite as part of the problem: "Solve this, **in two weeks, not
  six**."
- It heads off "there's always a better solution" debates. Anyone can propose
  an expensive solution, but it takes design insight to fit a small box.

### 3. Solution
- Present the **elements**, concrete enough that readers "get it" at a glance
  but abstract enough not to box in designers.
- A problem without a solution is **not pitchable**. It goes back to the
  shaping track.
- Techniques for helping readers see it:
  - **Embedded sketches:** draw fat-marker elements on top of a screenshot of
    the existing screen where the feature lives. Use this only for "linchpin"
    parts that everyone must see concretely.
  - **Annotated fat-marker sketches:** redraw them cleanly, with labels in a
    contrasting color or numbered callouts.
  - **Breadboards,** for flows. Raw breadboards look like "soup of words and
    arrows" to anyone who wasn't there, so tidy them up or pair them with
    sketches.
  - Add a **latitude disclaimer** wherever you drew more layout than you
    intended to prescribe, for example: "Designers should feel free to find a
    different arrangement."
- In text-only pitches, use breadboard notation (see `shaping.md`) and short
  descriptions of regions ("a box at the top of the dashboard containing the
  form link and a settings link, with the form preview to its right").

### 4. Rabbit holes
- Call out details worth spelling out to prevent trouble. Often a few lines of
  text are enough. Example: "URLs for payment forms will never live on custom
  domains in v1."
- Include each **patch** decided during shaping, so nobody downstream trips
  over it.

### 5. No-gos
- List anything deliberately excluded to fit the appetite or keep the problem
  tractable. Example: "No WYSIWYG editing of the form. Users can only upload a
  logo and edit header text on a separate Customize page."
- An empty no-go list on a big batch pitch almost always means the boundaries
  haven't been set.

## Optional but valuable

- A short **title** in the project's own language ("To-Do Groups", not
  "To-dos 2.0").
- **Evidence** such as screenshots or videos of the workaround people use
  today, support volume, or usage data that supports a trade-off. The book
  shows usage data used exactly this way.
- **Nice-to-haves** marked with `~`, clearly outside the core.

## Pitch review rubric

Use this when the user asks you to review a pitch. Run
`python3 scripts/check_pitch.py <file>` first for the mechanical checks, then
judge:

| Question | Red flag |
|---|---|
| Is there one concrete story, with a baseline? | Abstract complaints ("search is bad") or a list of feature requests |
| Is the problem worth the appetite? | A six-week appetite for a problem affecting a poor-fit segment |
| Is the appetite a budget, not an estimate? | "~8 story points", "about 120 hours", "should take 3 weeks" |
| Is the solution at the right altitude? | Wireframes, pixel specs, or copy-final UI; or a single sentence |
| Do the elements connect? Could a team start Monday? | Open questions like "TBD how X works", or "designer will figure out Y" for a core part |
| Are rabbit holes patched, not just listed? | "Risk: performance might be an issue" with no decision |
| Are no-gos explicit? | None listed, or phrased as "maybe later" instead of a firm out |
| Is it one project, not a grab-bag? | "2.0", "redesign", "refactor", or several unrelated problems |
| Does anything depend on another team mid-cycle? | Tangled interdependencies that the team can't control |

## Writing tips

- Lead with the story, not the feature.
- Write for someone who wasn't in the shaping room.
- Keep it to what the betting table needs. Implementation plans and task lists
  don't belong, because the team discovers those.
- Be honest about the trade-offs you made ("a little messy, but it drastically
  simplifies the problem").
