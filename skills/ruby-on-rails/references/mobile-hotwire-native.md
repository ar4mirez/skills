# Mobile apps from your Rails app: Hotwire Native

Sources: https://native.hotwired.dev (the iOS and Android guides, path
configuration and bridge references), plus turbo-rails
`Turbo::Native::Navigation`.

## The opinion

For a Rails team, **Hotwire Native is the default way to ship iOS and Android
apps.** A thin native shell (Swift or Kotlin) wraps your Rails-rendered
screens in native navigation, with native transitions, tabs, and modals. You
then upgrade screens in three steps, only where it pays off:

1. **Web screens.** Rails views, which covers most screens. You ship features
   once, instantly, without app-store review.
2. **Bridge components.** Native UI driven by your HTML: navbar buttons, menus,
   action sheets, haptics, share, permissions.
3. **Native screens.** Fully native SwiftUI or Kotlin, for maximum fidelity or
   native SDKs: maps, camera flows, offline editors.

Alternatives, and when to use them:
- **Rails as a JSON API plus fully native apps**, only when the app is mostly
  offline, graphics-heavy, or has a dedicated native team per platform. It
  multiplies work: three clients and API versioning.
- **React Native or Flutter:** not Ruby, and they add a second full UI stack.
  Only if a team with that expertise already exists.
- **RubyMotion:** legacy and maintenance-mode. Don't start new projects on it.

## Architecture overview

```
Rails app (one codebase)
├── HTML screens (the same views, native-aware via hotwire_native_app?)
├── /configurations/ios_v1.json, android_v1.json    (path configuration)
├── Stimulus BridgeComponents (@hotwired/hotwire-native-bridge)
└── JSON endpoints only for native screens that need data
iOS app (Swift, hotwire-native-ios)       Android app (Kotlin, dev.hotwire:*)
├── Navigator + tabs                        ├── HotwireActivity + NavigatorConfiguration
├── Bridge components (Swift)               ├── Bridge components (Kotlin)
└── Native screens (as needed)              └── Native screens (as needed)
```

## Rails side

### 1. Detect native clients

turbo-rails adds `hotwire_native_app?` to controllers and views. It matches a
"Hotwire Native" (or legacy "Turbo Native") user agent.

```erb
<%# app/views/layouts/application.html.erb %>
<% unless hotwire_native_app? %>
  <%= render "layouts/navbar" %>   <%# native provides its own navigation bar %>
<% end %>
<title><%= content_for(:title) || "Acme" %></title>  <%# becomes the native screen title %>
```

- Hide web-only chrome (the top nav, footers, breadcrumbs) in native. Keep
  content identical.
- Add a body class or data attribute (`data-native="true"`) for CSS tweaks
  instead of forking templates.
- Rarely, use a separate layout for native: `layout -> { hotwire_native_app? ?
  "native" : "application" }`.

### 2. Navigation responses

Native apps treat certain redirects as instructions:

```ruby
def create
  @invoice = Current.account.invoices.create!(invoice_params)
  recede_or_redirect_to invoice_path(@invoice), notice: "Created"  # dismiss modal / pop
end
```

- `recede_or_redirect_to`: pop the screen or dismiss the modal in native, or
  redirect on the web.
- `refresh_or_redirect_to`: refresh the current native screen.
- `resume_or_redirect_to`: do nothing in native.
- `*_or_redirect_back_or_to` variants also exist.

### 3. Serve the path configuration

```ruby
# config/routes.rb
namespace :configurations do
  get "ios_v1",     to: "ios#v1"
  get "android_v1", to: "android#v1"
end
```

```ruby
class Configurations::IosController < ApplicationController
  allow_unauthenticated_access

  def v1
    render json: {
      settings: {},
      rules: [
        { patterns: [ ".*" ], properties: { context: "default", pull_to_refresh_enabled: true } },
        { patterns: [ "/new$", "/edit$" ], properties: { context: "modal", pull_to_refresh_enabled: false } }
      ]
    }
  end
end
```

Rules:
- **Version the files** (`ios_v1`, `android_v1`). Breaking changes go into
  `_v2`, served to new app builds, and old versions stay up for old installs.
- **Order matters.** The first rule is a catch-all `".*"` default, and later
  rules override it.
- **Ship a bundled copy in the app too,** for first launch and offline use.
  The remote copy is loaded and cached afterwards.
- Known properties:
  - common: `context` (`default` or `modal`), `presentation` (`default`,
    `push`, `pop`, `replace`, `replace_root`, `clear_all`, `refresh`, `none`),
    `pull_to_refresh_enabled`, `animated`;
  - iOS: `view_controller`, `modal_style` (`large`, `medium`, `full`,
    `page_sheet`, `form_sheet`), `modal_dismiss_gesture_enabled`;
  - Android: `uri` (for example `hotwire://fragment/web` or
    `hotwire://fragment/web/modal/sheet`), `fallback_uri`, `title`.
- Validate the file with `ruby scripts/check_path_config.rb
  config/path_configuration/ios_v1.json`, or keep it as a static JSON file in
  `public/configurations/` and validate that. A template is in
  `assets/path-configuration.json`.
- Disable pull-to-refresh in modals, because it conflicts with the dismiss
  gesture and can wipe form input.

### 4. Bridge components (web side)

```bash
bin/importmap pin @hotwired/hotwire-native-bridge
```

Put a `BridgeComponent` (which extends a Stimulus Controller) in
`app/javascript/controllers/bridge/`. See
`assets/bridge_button_controller.js`, plus its Swift
(`assets/BridgeButtonComponent.swift`) and Kotlin
(`assets/BridgeButtonComponent.kt`) counterparts.

```erb
<%= link_to "Edit", edit_invoice_path(@invoice),
      data: { controller: "bridge--button", bridge_title: "Edit" } %>
```

```css
/* hide the web element only when this app build supports the component */
[data-bridge-components~="button"] [data-controller~="bridge--button"] { display: none; }
```

Key points:
- The `static component = "button"` name must match the native component's
  `name`.
- Hide web fallbacks with the `data-bridge-components` attribute, so older app
  builds without the component still see the web version.
- Good first components: a navbar button, a form submit button in the navbar,
  an overflow menu, share, a flash or toast in native style, and a sign-out
  handler.

### 5. Authentication

- Cookie sessions from the Rails authentication generator work as-is. The
  native web view keeps its cookies, so users sign in through your web sign-in
  page.
- Native screens that call JSON endpoints need the same session. Share the
  cookie with native HTTP clients (the iOS demo shows this), or issue a token
  through a small `api/` namespace. Keep that surface minimal.
- Keep sessions long-lived for native clients, and handle 401 by routing back
  to the sign-in URL. Hotwire Native shows the web sign-in page.

## Native side (minimum viable shells)

**iOS** (Xcode, Swift Package `https://github.com/hotwired/hotwire-native-ios`):

```swift
import HotwireNative
import UIKit

let rootURL = URL(string: "https://app.example.com")!

class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?
    private let navigator = Navigator(configuration: .init(name: "main", startLocation: rootURL))

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options: UIScene.ConnectionOptions) {
        window?.rootViewController = navigator.rootViewController
        navigator.start()
    }
}
// AppDelegate: Hotwire.loadPathConfiguration(from: [.file(localURL), .server(remoteURL)])
//              Hotwire.registerBridgeComponents([ButtonComponent.self])
```

**Android** (min SDK 28, Gradle `dev.hotwire:core` and
`dev.hotwire:navigation-fragments`, `INTERNET` permission):

```kotlin
class MainActivity : HotwireActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        enableEdgeToEdge()
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)   // FragmentContainerView → NavigatorHost
        findViewById<View>(R.id.main_nav_host).applyDefaultImeWindowInsets()
    }

    override fun navigatorConfigurations() = listOf(
        NavigatorConfiguration(name = "main", startLocation = "https://app.example.com",
                               navigatorHostId = R.id.main_nav_host)
    )
}
// Application.onCreate: Hotwire.loadPathConfiguration(context = this, location = PathConfiguration.Location(
//     assetFilePath = "json/configuration.json", remoteFileUrl = "https://app.example.com/configurations/android_v1.json"))
//   Hotwire.registerBridgeComponents(BridgeComponentFactory("button", ::ButtonComponent))
```

- Add tabs (multiple navigators) for the three to five top-level sections.
  Each tab is just a start URL.
- Keep the native repos small: shell, bridge components, a few native screens.
  Put them in `mobile/ios` and `mobile/android` in the monorepo, or in
  separate repos.

## Push notifications

Use **`action_push_native`** (by Basecamp, APNs + FCM):
1. `bundle add action_push_native`
2. `bin/rails g action_push_native:install`
3. Install its migrations and migrate.

This gives you `ApplicationPushNotification`, `ApplicationPushDevice`, a
delivery job, and `config/push.yml`. Keep the keys in credentials. Native
apps register their device token with a small authenticated endpoint. Send
notifications from model methods or jobs, just like mail
(`deliver_later`-style), never from `after_save`.

## App Store and Play Store gotchas

- **Apple guideline 4.2 (minimum functionality)** rejects apps that are "just
  a website." Real native navigation, tabs, a few bridge components, and push
  notifications are what get approved.
- If users can sign up in the app, **in-app account deletion** is required.
  Third-party login needs Sign in with Apple, or an equivalent
  privacy-focused option.
- **Give App Review a working demo account.** Don't sell digital goods or
  show upgrade prompts in the app unless you've read the current in-app
  purchase rules. B2B apps where accounts are bought on the web are usually
  fine.
- **Register developer accounts as the organization,** which needs a D-U-N-S
  number for Apple, so start early. New *personal* Google Play accounts must
  run a closed test before publishing.

## Release strategy

- Web changes ship instantly to every app. Only native code (components,
  screens, configuration defaults) needs store review.
- Bump the path configuration version when an app release depends on new
  rules or components.
- Gate new bridge-dependent UI on `data-bridge-components` or the app version
  in the user agent, so old builds keep working.
- Test on real devices. Check that Rails request tests with a native user
  agent cover native-specific rendering.

## Checklist for "we want mobile apps"

- [ ] Views are responsive and touch-friendly (buttons large enough,
      mobile-first layout)
- [ ] `hotwire_native_app?` hides web navigation, and `<title>` is set on every
      page
- [ ] Forms and modals use `recede_or_redirect_to`, and new or edit pages open
      as modals via path config
- [ ] Path configuration is versioned per platform, bundled and remote, and
      validated
- [ ] Two or three bridge components (navbar button, menu, share) are in place
- [ ] Authentication works in the web view, and 401s route to sign-in
- [ ] App icons, splash screen, push notifications (`action_push_native`),
      and deep links (universal links / app links) are set up
- [ ] Store rules covered: 4.2 native value, account deletion, Sign in with
      Apple if social login, demo account for review
- [ ] Store listings exist, with TestFlight and internal testing tracks
