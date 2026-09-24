# Shaping: boundaries, elements, and rabbit holes

Source: *Shape Up*, chapters 2–5 (https://basecamp.com/shapeup/1.1-chapter-02
through /1.4-chapter-05). This is a paraphrased working guide.

## Contents
- Who shapes, and how
- Step 1: Set boundaries (appetite, narrow the problem, grab-bags)
- Step 2: Find the elements (breadboards, fat-marker sketches)
- Step 3: Risks and rabbit holes (review, patch, declare out of bounds, cut, expert review)
- Exit criteria for each step

## Who shapes, and how

- Shaping is **design work that is also strategic**. It combines interface
  ideas, technical possibility, and business priority. One generalist can do
  it, or two or three people together. You don't have to be a programmer, but
  you must be technically literate: able to judge what's easy, hard, or
  possible in *this* system.
- Shaping is **closed-door, fast, and frank**. You work alone or with one
  trusted partner who speaks your shorthand. Your artifacts are allowed to be
  unreadable to outsiders.
- Shaping is **its own track**, and it can't be scheduled. Work in progress
  stays private until it's bet on, so a shaper can shelve or drop it with no
  cost. Nothing about shaping is a commitment, and there's no conveyor belt.

When helping a user shape, play the trusted partner. Move fast, propose
alternatives, and challenge assumptions.

## Step 1: Set boundaries

You need three things before moving on: **a raw idea, an appetite, and a narrow
problem definition.**

### Respond to raw ideas with a soft no

The default first response is **"Interesting. Maybe some day."** It keeps every
option open without committing. Don't log it in a backlog. A "yes" at first
contact commits to something nobody understands yet. A flat "no" shuts down
something that new information might reframe. Keep a poker face: don't signal
enthusiasm that sets expectations.

### Set the appetite

Ask how much time this idea *deserves*, not how long it will take. Frame the
question as: is this worth a quick fix? A full cycle? Would we redesign what
exists to fit it? Would we only do it as a minor tweak?

- **Small batch:** one designer plus one or two programmers for **1–2 weeks**.
  Several of these are batched into one cycle.
- **Big batch:** the same team for a full **six-week** cycle.
- **Too big for six weeks?** First narrow the problem. If it still doesn't fit,
  carve off a meaningful part that does fit six weeks and shape only that.
- **"Good" is relative to the appetite.** A hot dog is the perfect meal when
  you're hungry and in a hurry. A flat textarea can be the right answer at a
  small appetite, where a full data model would be right at a big one.

### Narrow down the problem

Flip the question from *"What could we build?"* to *"What's really going
wrong?"* Find the moment the current workflow breaks down.

- Ask customers **when** they wanted the thing, and what they were doing at the
  time. Don't ask **why** they want it, or what it should look like.
- Book example: a request for complex permission rules turned out to be one
  person archiving a file without realizing it vanished for everyone else. The
  fix was a warning on the archive action, which took one day instead of six
  weeks.
- Book example: "we want a calendar" became "help me see free spaces so I can
  schedule something." That led to the Dot Grid (see `case-studies.md`).
- If you can't find a specific pain point, the appetite also limits how much
  research is worth doing. If it isn't critical, walk away. It will come back
  with better context if it matters.

### Watch out for grab-bags

"Redesign the Files section", "Files 2.0", and "refactor the billing code" have
no single problem, no start, and no definition of done. The "2.0" label is a
tell-tale sign. Reframe it around a specific problem, such as "We need to
rethink Files because sharing multiple files takes too many steps." Or split it
into separately shaped projects, like "Better file previews" and "Custom folder
colors", each with its own appetite.

**Exit criteria:** a one-sentence problem tied to a specific story, an explicit
appetite (small or big batch, with a number of weeks), and agreement that it's
worth shaping further.

## Step 2: Find the elements

Get from words to the **elements** of a solution at a level of abstraction
above wireframes, so you can explore broadly and quickly. Four questions:

1. Where in the current system does the new thing fit?
2. How do you get to it?
3. What are the key components or interactions?
4. Where does it take you?

### Breadboarding (for flows)

The term is borrowed from electronics, where a breadboard has all the
components and wiring but no industrial design. There are three primitives,
**all written in words, never pictures**:

- **Places:** things you can navigate to, such as screens, dialogs, and menus.
  Write the name and underline it.
- **Affordances:** things the user can act on, such as buttons, fields, and
  also interface copy (reading copy is an act). List them under the place they
  belong to.
- **Connection lines:** arrows from an affordance to the place it takes the
  user.

In plain text, write breadboards like this:

```
Invoice
-------
- Pay button  ──>  Pay Invoice

Pay Invoice
-----------
- CC / ACH fields
- [ ] Autopay in the future
- Submit  ──>  Confirm

Confirm
-------
- Thank-you message
- Print receipt
- "Autopay enabled" callout (if chosen)
```

As you breadboard, **play the use case through**. Each word you write under a
line tends to provoke the real questions. In the Autopay example: does turning
it on also pay the current invoice? How does the customer turn it off? Try
radically different topologies cheaply. In that example, the shapers moved
Autopay from "a button on the invoice" to "an option while paying." Stop when
the flow serves the use case.

### Fat-marker sketches (for visual or 2D problems)

Use these when the spatial arrangement *is* the problem, so a breadboard would
miss the point. Draw with strokes so broad that detail is impossible. In text,
describe the sketch as regions and their relationships, not coordinates or
styles. Here's the To-Do Groups example: loose to-dos sit above the first
divider, grouped to-dos sit below, and there's an add affordance per group,
falling back to the existing item menu if that clutters the list. Watch for
getting attached to an incidental layout element, such as a sidebar you
happened to draw.

### Elements are the output

End this step with a short list of **concrete, narrow elements**, for example:
- a 2-up monthly grid;
- dots for events, with no spanned pills;
- an agenda list below the grid that scrolls to a day when you tap a dot.

This is far narrower than "monthly calendar" while leaving every visual
decision to the designer. It isn't a spec. It's more like the boundaries and
rules of a game.

**Room for designers.** Any mockup you make, especially if you're senior, will
be taken as direction. Leaving detail out is what gives the builders room.

**Exit criteria:** a named approach and a handful of elements that
solve the narrowed problem within the appetite. At this point it's still
private and still rough.

## Step 3: Risks and rabbit holes

**Goal:** make the project's time-to-ship **thin-tailed**. It might run a week
over, but never three times over. A single hole that costs the team two weeks
burns a third of a six-week budget. Some holes have no solution at all. The
book's example is a home-screen redesign that was bet on unshaped and later
abandoned.

### Review in slow motion

Walk the use case step by step through the elements. Then ask of every part:
- Does this require **new technical work** we've never done before?
- Are we making **assumptions about how the parts fit together**?
- Are we assuming **a design solution exists** that we couldn't come up with
  ourselves?
- Is there **a hard decision** we should settle now so it doesn't trip up the
  team?

Also look for: missing states (empty, completed, error, permissions),
interactions with existing features (completed items, notifications, mobile,
search), data migrations, performance hot paths, and third-party dependencies.

### Four moves for each risk found

1. **Patch the hole.** Dictate a specific, possibly imperfect solution in the
   shaped concept. For example, in To-Do Groups, completed items stay exactly
   where they were and just get the group name appended. That's a little messy,
   but it cuts off a huge tail of risk. Trade-offs like this are hard for a
   team to make under deadline pressure, which is why the shaper makes them.
2. **Declare out of bounds.** Name the use cases you're explicitly *not*
   covering. For example, group notifications applied only to posting messages,
   not to to-do assignment or chat mentions. These become **no-gos** in the
   pitch.
3. **Cut back.** Remove appealing but unnecessary parts, such as color-coding
   the groups. You can mention them as nice-to-haves, but the project must be
   valuable without them.
4. **Present to technical experts.** Do this privately, in a
   "friendly-conspiratorial" way ("here's something I'm thinking about, I'm not
   ready to show anyone yet"). Ask "is this possible **in six weeks**?", not
   "is this possible?" Walk through the concept from the beginning on a
   whiteboard ("keep the clay wet") rather than sending a document. Stick to
   your worked concept first, then invite simplifications. You're hunting for
   **time bombs**.

If the expert review finds problems, go back for another round of shaping.
That's a success, not a failure.

**Exit criteria:** elements plus patches for known rabbit holes plus fences
around out-of-bounds areas. With those in place, it's ready to write as a pitch
(see `pitch.md`).

## Output checklist for any shaping help

- [ ] Appetite stated in weeks (small batch or big batch), and never derived
      from an estimate
- [ ] Problem told as one specific story, with the baseline (what people do
      today)
- [ ] Solution as elements (breadboard or fat-marker description), with no
      wireframes
- [ ] Each rabbit hole either patched, declared out of bounds, or cut
- [ ] No-gos listed explicitly
- [ ] Still framed as an option, not a commitment
