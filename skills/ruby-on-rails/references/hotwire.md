# Hotwire: Turbo + Stimulus

Default to server-rendered HTML. Choose the lightest tool that gets the job
done, in this order:
**Turbo Drive → morphing page refresh → Turbo Frame → Turbo Stream → Stimulus
→ a JS island.**

## Turbo Drive (free)

- It's on by default: links and forms become fetch requests plus a body swap.
  Keep it on.
- **Form responses:** on failure, `render :new, status: :unprocessable_entity`.
  On success, `redirect_to`. Turbo requires one or the other, and a 200
  response to a form submission renders nothing.
- Opt out per element with `data-turbo="false"` only for downloads or full
  reloads.
- Use `data-turbo-confirm="Are you sure?"` on the form or `button_to`
  instead of `rails-ujs` `confirm`. Use `button_to ..., method: :delete`
  rather than `link_to` with a method.

## Morphing page refreshes (Turbo 8), the default for live updates

```erb
<%# app/views/layouts/application.html.erb, in <head> %>
<%= turbo_refreshes_with method: :morph, scroll: :preserve %>
```

```ruby
class Invoice < ApplicationRecord
  broadcasts_refreshes          # any change → subscribers re-fetch and morph
end
```

```erb
<%= turbo_stream_from @invoice %>   <%# on the show page %>
```

This replaces most hand-written `turbo_stream` templates. The page simply
re-renders and morphs, so the logic stays in one template. Mark volatile
elements with `data-turbo-permanent`, or ignore them during morphing where
needed. Refreshes are debounced, so bursts are cheap.

## Turbo Frames: scoped navigation

Use frames for inline editing, tabs, pagination within a panel, and lazy
panels.

```erb
<%= turbo_frame_tag dom_id(invoice) do %>
  <%= render invoice %>
  <%= link_to "Edit", edit_invoice_path(invoice) %>   <%# response must contain the same frame id %>
<% end %>

<%= turbo_frame_tag "activity", src: invoice_activity_path(@invoice), loading: :lazy %>
```

- Frame responses should render the full page, with the frame inside it.
  Don't make frame-only endpoints; Turbo extracts the matching frame.
- Use `target: "_top"` to break out of a frame. Use `data-turbo-action:
  "advance"` to update the URL.

## Turbo Streams: targeted mutations

Use streams when one action changes several unrelated parts of the page, or
for broadcasts that shouldn't refetch.

```ruby
def create
  @comment = @post.comments.create!(comment_params)
  respond_to do |format|
    format.turbo_stream   # create.turbo_stream.erb
    format.html { redirect_to @post }
  end
end
```

```erb
<%# create.turbo_stream.erb %>
<%= turbo_stream.append "comments", @comment %>
<%= turbo_stream.update "comments_count", @post.comments.size %>
```

- **Always keep an HTML fallback** (`format.html`).
- The actions are `append`, `prepend`, `replace`, `update`, `remove`,
  `before`, `after`, and `refresh`. Keep custom stream actions rare and
  documented.
- For broadcasts, prefer `broadcasts_refreshes`, or `broadcast_*_later_to` from
  model `after_commit` callbacks. They run in a job via Solid Cable.

## Stimulus conventions

```js
// app/javascript/controllers/clipboard_controller.js
import { Controller } from "@hotwired/stimulus"

export default class extends Controller {
  static targets = ["source"]
  static values = { successMessage: { type: String, default: "Copied!" } }

  copy() {
    navigator.clipboard.writeText(this.sourceTarget.value)
    this.element.dataset.copied = "true"
  }
}
```

```erb
<div data-controller="clipboard" data-clipboard-success-message-value="Link copied">
  <input data-clipboard-target="source" value="<%= invitation_url %>" readonly>
  <button data-action="clipboard#copy">Copy</button>
</div>
```

- Controllers are **small and generic** (`clipboard`, `toggle`,
  `auto-submit`, `dialog`), not page-specific (`invoice_page`).
  Configure them with values and targets.
- Keep state in the DOM (data attributes, classes), not in JS variables that
  morphing wipes.
- Clean up in `disconnect()`. Don't fetch JSON and render HTML in JS. Let the
  server render, and use a frame or stream.
- For third-party libraries, `bin/importmap pin <package>`. If a library
  needs a build step, that's the signal to consider jsbundling, for that island
  only.

## Forms that feel instant

- Use `form_with` (remote by default via Turbo). Add
  `data-turbo-submits-with="Saving…"` to buttons.
- **Auto-save or filter-as-you-type:** a tiny `auto-submit` Stimulus controller
  calling `this.element.requestSubmit()` (debounced), targeting a frame.
- Validation errors come from the server re-render (422). Don't duplicate
  validations in JS.

## Testing Hotwire

- Request tests assert HTML and turbo-stream responses:
  `assert_turbo_stream action: :append, target: "comments"`.
- System tests (Capybara) cover the interactive flows that matter. Rely on
  Capybara's waiting matchers, not `sleep`.
- In model tests, check broadcasts with `assert_turbo_stream_broadcasts`
  (from turbo-rails test helpers).
