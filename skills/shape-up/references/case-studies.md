# Case studies (paraphrased from *Shape Up*)

Use these as models for the *shape* of your outputs: how narrow the problem
is, how rough the solution is, and where the boundaries sit. Chapter links are
to https://basecamp.com/shapeup.

## Dot Grid calendar (ch. 2–4): narrowing a huge request
- **Raw idea:** customers asked for "a calendar." A full calendar takes about
  six months: drag-and-drop, multi-day wrapping, multiple views, resizing,
  color coding, and desktop vs. mobile differences. Only about 10% of
  customers had used past calendars.
- **Appetite:** one six-week cycle. The question became which *tenth* of a
  calendar to build.
- **Narrowing:** the shapers asked a customer *when* she wanted a calendar. Her
  office used a chalkboard calendar for meeting rooms. Working from home, she
  had to drive in to check for a free slot. So the problem was "see free
  spaces," not "do everything a calendar does."
- **Elements:** a 2-up monthly read-only grid, one dot per event (multi-day
  events just repeat the dots), and an agenda list below that scrolls to the
  tapped day.
- **No-gos:** dragging events, spanning pills, colors, and categories.
- **Result:** the final design kept the sketch's structure, fully designed.

## Permissions → archive warning (ch. 3): the problem beneath the request
- A customer asked for complex permission rules, potentially six weeks of work.
- The real issue: someone archived a file without knowing it disappeared for
  everyone else.
- **Solution:** a warning on the archive action explaining the impact. One day
  of work.

## Files 2.0 (ch. 3): a grab-bag failure
- "Files 2.0" was kicked off without a defined problem, and nobody knew what
  "done" meant. It turned into a mess.
- **Recovery:** they split it into shaped projects, such as "Better file
  previews" and "Custom folder colors," each with its own appetite. Both
  shipped.

## Autopay (ch. 4): breadboarding a flow
- **Product:** invoicing. Idea: let customers' customers pay future invoices
  automatically.
- **First breadboard:** Invoice → "Turn on Autopay" → Setup Autopay (CC fields,
  FI logo, Submit) → Confirm. This raised the question of whether the current
  invoice gets paid.
- **Pivot:** make Autopay an option *while paying*. Invoice → Pay → Pay Invoice
  (with "Autopay in the future") → Confirm (receipt, plus an "Autopay enabled"
  callout). ACH came out of the sketch as supported too.
- **Turning it off:** customers had no accounts, only tokenized links, and
  building username/password flows was too much for the appetite. **Decision:**
  the invoicer disables Autopay from the existing customer detail page, and
  the customer asks the invoicer to do it.
- **Elements:** an "Autopay?" checkbox on the existing pay screen, and a
  "Disable Autopay" option on the invoicer's side.

## To-Do Groups (ch. 4–6): fat-marker sketch, patching a hole, cutting back
- **Problem:** people faked dividers with to-dos like "--- Needs testing ---".
- **Elements:** a divider splits the list into loose to-dos (above the first
  divider) and groups (below it). Add an affordance per group if it fits
  visually, otherwise fall back to the existing item action menu.
- **Hole found:** how to show *completed* items. **Patch:** leave completed
  items exactly where they were and append the group name to each. It's a
  little messy, but it removes a deep design problem the team would have had
  to solve under deadline.
- **Cut:** color-coded groups, mentioned only as a nice-to-have.
- **Pitch:** screenshots of the workaround (the problem), then five fat-marker
  sketches (the solution), with the rabbit holes motivating some sketches.

## Group notifications (ch. 5): declaring out of bounds
- The idea was to notify "Programmers" instead of ticking five people.
  Groups could apply in many places, like to-dos and chat mentions.
- **Boundary:** the core value was a faster flow for posting messages. Every
  other use was declared **out of bounds**.

## Payment Form (ch. 6): embedded sketches, rabbit hole, no-go
- **Breadboard:** Dashboard (Go to Form, Send Form Link, Change Form Settings)
  → Simple Payment Form (fields, CC, Submit, logo) → Thank You.
- An **embedded sketch** drew the new box on a real dashboard screenshot,
  because this was the linchpin that people had to see. The pitch included a
  disclaimer that designers could choose a different layout.
- **Rabbit hole patch:** no custom domains for form URLs in v1.
- **No-go:** no WYSIWYG form editing, only logo and header text on a separate
  Customize page.

## Home-screen client projects (ch. 5): what happens without de-risking
- The project was bet on the assumption that "the designer will figure it out."
  Nobody found a viable design within six weeks, and it was abandoned, then
  later rethought. The lesson: validate that a solution *exists* while
  shaping.

## Clients in Projects (ch. 11–12): choosing the first piece
- **Parts:** Client Access (new partial-visibility model with caching
  implications), Client Management, and a Visibility Toggle on every item.
- **Team:** one designer and one programmer. The designer chose the **toggle**
  first because it was core, small, and novel. He experimented with raw
  affordances in real templates.
- Meanwhile, the programmer spiked the access model. He then briefly wired the
  toggle to appear on all content types and persist its state, but not yet to
  change visibility.
- About three days in, a manager saw the toggle demoed, a few tweaks followed,
  and it was **done**. One piece was designed, built, demoed, and settled.
- **Scope language that emerged:** "After Bucket Access is done we can
  implement Invite Clients. Then we'll Update Recording Visibility when people
  flip the Visibility Toggle."

## Message Drafts (ch. 12): scopes emerging from work
- **End of week one:** tasks were done, but nothing was demoable. The team
  carved out **Start New** and finished it.
- Remaining tasks were split into **Locate**, **Trash**, and **Save/Edit**.
  Digging into Save/Edit revealed **Send**, **Store**, and **Reply** (a special
  case for drafts of replies).
- The team knew the scopes were right when the whole project was visible at a
  glance and no scope could hide a big task.

## Notify (ch. 13): splitting a stuck scope
- "Notify" sat still on the hill for six days. It was really three parts: the
  email design (near the top), email delivery (almost done), and the in-app
  menu (not started).
- They split it into **Email**, **Deliver**, and **Hey Menu**, and each moved
  independently from then on.

## Recurring events (ch. 13): reading a hill chart
- "Future-applying edits" was a third of the way uphill, with significant
  unknowns. "Per-occurrence permalinks" and "Global recurring events" were
  both downhill, and the latter was nearly done. A manager could see at a
  glance where to help.

## Product modes: HEY and Hill Charts (ch. 9)
- **HEY:** about a year in R&D mode (the CEO, the CTO, and a senior designer
  spiking the core), about a year in production mode (all teams), then two
  cleanup cycles, with a heavily cut feature set at the July 2020 launch.
  Every cycle was bet on individually.
- **Hill Charts:** an experimental feature on an existing product. The first
  cycle built a version good enough for internal use, with no commitment to
  ship. After gaining confidence, they shaped a round-out project, bet a second
  cycle, and shipped it.
