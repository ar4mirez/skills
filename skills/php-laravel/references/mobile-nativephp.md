# Mobile and desktop with NativePHP

**Default:** ship iOS and Android apps with **NativePHP Mobile 4**, a
separate Laravel app that runs *on the device* and talks to your main
Laravel app's API. Choose a fully native app (Swift/Kotlin) only when the
product needs platform depth NativePHP can't reach, and point it at the
same API.

Sources: the NativePHP Mobile v4 docs (nativephp.com/docs/mobile/4) and the
`nativephp/mobile` package source. The package moves fast, so check
its changelog before quoting details.

## Contents
- How it works
- The two-app shape
- Setup and development loop
- UI: EDGE components and web views
- Data on the device
- Auth against your API
- Security: the bundle is public
- Native features and plugins
- Publishing
- Desktop
- Alternatives

## How it works

- A pre-compiled PHP runtime (built with the embed SAPI, linked as
  `libphp`) ships inside a Swift/Kotlin shell. **There's no web server.**
  PHP runs in-process and stays warm between interactions.
- **NativePHP Mobile currently embeds PHP 8.4**, so code in the mobile app
  must be 8.4-compatible. Don't use PHP 8.5 syntax (pipe `|>`,
  `clone(..., [...])`, `array_first()`) there.
- UI is built from **EDGE components**: Blade components that render as
  real native views. A web view is available too.
- Device APIs (camera, biometrics, secure storage, push, geolocation,
  scanner, share) come through PHP facades and plugins.

## The two-app shape

```
acme/            the main Laravel app: source of truth, Postgres, Sanctum API
acme-mobile/     a new Laravel app + nativephp/mobile: UI, local SQLite cache, API client
```

- Keep business rules on the server. The mobile app renders, caches, and
  queues offline writes; the server validates and decides.
- Share the API contract, not the code: the main app's API resources and
  Form Requests are the contract. Version it (see `http-and-api.md`).
- A small shared Composer package for DTOs is acceptable if it stays
  8.4-compatible and framework-light.

## Setup and development loop

```bash
laravel new acme-mobile && cd acme-mobile
composer require nativephp/mobile
# .env: NATIVEPHP_APP_ID=com.acme.mobile  (and NATIVEPHP_DEVELOPMENT_TEAM for iOS signing)
php artisan native:install      # choose ICU-enabled binaries if you need intl (Filament does)
php artisan native:run          # build and run on a simulator or device
php artisan native:watch        # hot reload while developing
php artisan native:jump         # preview on a device with the Jump app, without a full build
```

Needs Xcode for iOS and Android Studio / SDK for Android. Windows works
natively, but not under WSL.

## UI: EDGE components and web views

- Build screens with EDGE components (lists, top bar, bottom navigation,
  bottom sheets, text inputs, buttons, pull-to-refresh). They feel like
  Livewire but render native views.
- Keep screens thin: fetch through an API client class, map responses to
  DTOs, and render.
- Respect the safe areas and platform navigation patterns. Apple rejects
  "a website in a wrapper" apps (guideline 4.2), and native components are
  how you avoid that.

## Data on the device

- NativePHP uses **SQLite on the device** automatically: it creates the
  database and runs your migrations at app start.
- Migrations run on every user's device on update. **Never write a
  destructive migration** in the mobile app, and test migrations on
  release builds before shipping.
- Seed reference data with migrations (they run exactly once per install).
- Treat the local database as a cache plus an outbox: sync from the API,
  and queue offline writes with a client-generated UUID so the server can
  deduplicate them.

## Auth against your API

- The device can't be trusted, so normal Laravel session auth doesn't
  apply. Authenticate against the main app.
- **Sanctum tokens** (set `expiration`) or OAuth via Passport or WorkOS.
  For OAuth, use `Browser::auth(...)` with a unique
  `NATIVEPHP_DEEPLINK_SCHEME` redirect.
- Store tokens in **SecureStorage**, not SQLite or `.env`.
- A token existing doesn't mean the user is authenticated. Exercise it, and
  re-authenticate on 401.
- The login endpoint has no CSRF protection from a device: rate-limit it
  hard, and consider an app-level key that's only for that endpoint.

## Security: the bundle is public

Everything you ship (PHP source, views, and the bundled `.env`) can be
read by anyone who unpacks the APK or IPA. Encrypting the bundle doesn't
help, since the key ships with it.
- No secrets in the mobile app. Use `cleanup_env_keys` in
  `config/nativephp.php` to strip keys from the bundled `.env`.
- Sensitive logic and third-party API keys stay on the server, behind
  authenticated endpoints.
- Generate per-install keys at first run where you need local encryption.

## Native features and plugins

- Core plugins cover biometrics, camera, microphone, geolocation, network
  status, push notifications (Firebase), secure storage, sharing, and
  scanning.
- Custom native code goes in plugins with bridge functions
  (`php artisan native:plugin:create` scaffolds one).
- Check `Network::status()` before API calls, and fall back to the local
  cache.

## Publishing

- `php artisan native:package` builds signed release artifacts, and
  `native:release` handles versioning. Bifrost (NativePHP's hosted
  service) can build and submit in the cloud.
- Bump build numbers every release. Test on real devices for both
  platforms before submitting.

## Desktop

**NativePHP Desktop 2** (`nativephp/desktop`) packages a Laravel app as a
macOS, Windows, or Linux desktop app (Electron shell with a bundled PHP).
The same rules apply: the bundle is readable, secrets stay on a server,
and local data is SQLite.

## Alternatives

- **Responsive web + PWA** from the main app (Livewire or Inertia) when you
  don't need device APIs or store presence.
- **Fully native (Swift/Kotlin) or React Native** clients against the same
  Sanctum API, when a mobile team exists or the app needs deep platform
  integration.
