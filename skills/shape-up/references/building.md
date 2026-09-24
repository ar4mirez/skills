# Building: hand over, get one piece done, map the scopes

Source: *Shape Up*, chapters 10–12 (https://basecamp.com/shapeup/3.1-chapter-10
through /3.3-chapter-12). This is a paraphrased working guide.

## Contents
- Assign projects, not tasks
- Done means deployed
- Kick-off and orientation
- Imagined vs. discovered tasks
- Get one piece done (vertical integration; choosing the first piece)
- Map the scopes (discovery, signs that scopes are right, layer cakes, icebergs, chowder, `~`)

## Assign projects, not tasks

- No taskmaster or architect splits the pitch up front, because that shreds
  it into disconnected pieces. The **team takes the whole project** within the
  pitch's boundaries, and defines its own tasks and approach.
- The reason: nobody can predict up front everything that will need doing. The
  people doing the real work are best placed to spot missing pieces and adjust.
  Assigned tasks let each person finish their piece without owning the whole.
- This isn't unlimited freedom. The shaping set the boundaries, and the team
  fills in the outline with real design and implementation.

If a user asks you to "break this pitch into tickets and assign them", explain
the paper-shredder problem. Offer instead a kick-off brief and a suggested
**first piece**, and let the team discover tasks. If their tooling requires
tickets, create them *per scope, as scopes are discovered*, with the team
owning them.

## Done means deployed

- The project must be deployed within the cycle. Small batch projects deploy
  whenever they're ready, as long as it's before the cycle ends.
- Testing and QA happen **inside** the cycle.
- Help docs, marketing, and announcements are thin-tailed and usually done by
  other teams. They can land in cool-down.

## Kick-off and orientation

- Kick-off means creating the project space, posting the pitch or a distilled
  version of it, and holding a call for questions.
- **The first days look like nothing.** No tasks get checked, nothing gets
  deployed, and the team is quiet. People are learning the relevant code,
  rethinking the pitch, and hitting short dead ends to find a starting point.
  Asking for status now just pushes exploration underground. Let people say
  "I'm still figuring out where to start."
- **Rule of thumb:** step in only if the silence hasn't started breaking after
  about **three days**.

## Imagined vs. discovered tasks

- **Imagined tasks** are the ones you assume by thinking about the problem.
  **Discovered tasks** turn up by doing the real work, and they make up the
  true bulk of the project and its hardest parts. Examples: the new button has
  no obvious place on mobile; a layout needs explanatory copy that breaks it;
  a migration reveals a method that must change later.
- So task lists **grow** as the project progresses. That's normal, not scope
  failure.
- The way to find the real work is to start doing real work, on something
  meaningful.

## Get one piece done

Aim for something **tangible and demoable in the first week or so**: one slice
integrated vertically, from UI to working code. Avoid horizontal layers, where
front-end screens aren't wired to anything and back-end logic has nothing to
click. With layers, "lots of things are done but nothing is really done."

- **Programmers don't wait for design.** The pitch has enough to start
  back-end modeling on day one.
- **Affordances before pixel-perfect screens.** The first UI handed to a
  programmer can be raw HTML: fields, buttons, where the data shows. Settle
  font, color, spacing, and layout later. First make it work, then make it
  beautiful. Even a rough screen encodes real decisions, such as asking for
  arrival time but not departure time, or using a pulldown with option groups
  instead of a date picker.
- **Program just enough for the next step.** Early back-end work can be
  strategically patchy: a controller with no model, mock data, routes between
  stub screens, or hard-coded HTTP auth instead of a login system. The point is
  back-and-forth between design and code on the *same* piece, in turns, not one
  big hand-off.
- **Start in the middle.** Don't build login, setup, or admin first. Jump to
  the interesting problem and stub everything else.

### Choosing the first piece

The first piece should be:
1. **Core.** Without it, nothing else matters. For example, the visibility
   toggle in Clients in Projects, not renaming a client.
2. **Small.** Finishable in a few days, so it builds momentum.
3. **Novel.** Among core and small candidates, pick the one you've never done
   before, because it removes the most uncertainty. The UI for adding clients
   mostly duplicated adding users, so it would have taught the team nothing.

## Map the scopes

### Organize by structure, not by person

Lists like "Designer tasks" and "Programmer tasks" produce completed tasks that
don't add up to finished parts. Organize instead by the parts of the project
that can be completed independently. The non-software analogy is a fundraiser:
organize by Food Menu, Venue Setup, and Light/Sound, not by volunteer.

**A scope** is an integrated slice (front end plus back end) that can be built,
integrated, and finished **independently**, in **a few days or less**. It's
bigger than a task and much smaller than the project. In practice, a scope is a
to-do list, and its tasks are the items.

### Scopes are discovered, not planned

- "You need to walk the territory before you can draw the map." At the start
  there's only the shaped outline and some scattered tasks, so don't force
  groupings.
- Expect accurate scopes around the **end of week one or start of week two**.
  Expect them to be redrawn and renamed at first.
- Scopes arise from **interdependencies**, meaning what has to be finished
  together before you can call a piece "done."
- **Scopes become the language of the project.** "After Bucket Access is done
  we can implement Invite Clients." Report status in scope names, not task
  minutiae.

Worked evolution (Message Drafts, see `case-studies.md`): Unscoped → Start New
(done) → Locate, Trash, Save/Edit → Save/Edit split into Send, Store, and
Reply.

### How to know the scopes are right

Signs that they're right:
- You can see the whole project, and nothing worrying is hidden in the details.
- Conversations flow, because the scopes give you the words.
- New tasks have an obvious home.

Signs that they need redrawing:
- It's hard to say how done a scope is. That usually means it holds unrelated
  problems, so factor one out.
- The name isn't unique to the project: "front-end", "bugs", "misc". These are
  grab bags and junk drawers. File bugs under the scope they affect.
- It's too big to finish soon. It has turned into its own master to-do list, so
  split it.

### Layer cakes, icebergs, and chowder

- **Layer cake:** thin, evenly spread back-end work under the UI, as in a
  typical CRUD or information app. You can judge its size by UI surface. Keep
  design and code tasks in the same scope. This is the default.
- **Iceberg:** a small UI over a big back end, such as one form over complex
  business logic. Factor the UI into its own scope if it's independent, and
  split the back end into separate concerns, each its own scope. **Upside-down
  iceberg:** a complex UI over a simple model, such as multi-day events
  wrapping across a calendar grid. **Always question an iceberg before
  accepting it.** Is the complexity necessary and irreducible? Is there a
  simpler UI, or a back end with fewer interdependencies?
- **Chowder:** a list for loose tasks that don't fit any scope. It's fine, but
  if it grows past about **3–5 items**, there's a scope hiding in it.

### Mark nice-to-haves with `~`

When you find something that could be cleaned up, an edge case, or a possible
improvement, record it on the relevant scope with a leading `~`. Must-haves
define when a scope is done. `~` items can linger after a scope is done, and
most never get built. Marking an item with `~` *is* the scope hammering. The
`~` can also mark an entire scope as optional.

Use `assets/scope-map-template.md` to produce a scope map.
