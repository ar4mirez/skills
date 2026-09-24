# Queues, scheduling, and real-time

**The rule: requests do the minimum; everything slow, retryable, or
external goes to a queue, and every job is safe to run twice.**

## Contents
- What goes on a queue
- The job shape
- Idempotency, uniqueness, and debouncing
- After commit
- Failures, retries, and timeouts
- Drivers: database first, then Redis + Horizon
- Routing jobs to queues
- Workers in production
- Scheduling
- Notifications and mail
- Real-time with Reverb
- Small async work without a job

## What goes on a queue

Email, notifications, webhooks out, PDF and CSV generation, image
processing, search indexing, embeddings and AI calls, third-party API
calls, and anything that takes more than about 200 ms of real work.

## The job shape

```php
#[Tries(5)]
#[Backoff([10, 60, 300])]
#[DeleteWhenMissingModels]
final class SendInvoiceReminder implements ShouldBeUnique, ShouldQueue
{
    use Queueable;

    public function __construct(public readonly Invoice $invoice) {}

    public function uniqueId(): string
    {
        return (string) $this->invoice->id;
    }

    public function handle(): void
    {
        $invoice = $this->invoice->fresh();

        // Idempotent: a retry or a duplicate dispatch must not email twice.
        if ($invoice === null || ! $invoice->isOverdue() || $invoice->reminded_at?->isToday() === true) {
            return;
        }

        Notification::route('mail', $invoice->customer_email)->notify(new InvoiceReminder($invoice));
        $invoice->forceFill(['reminded_at' => now()])->save();
    }
}
```

- Configure with attributes (Laravel 13): `#[Tries]`, `#[Backoff]`,
  `#[Timeout]`, `#[FailOnTimeout]`, `#[MaxExceptions]`, `#[UniqueFor]`,
  `#[DebounceFor]`, `#[Queue]`, `#[Connection]`, `#[WithoutRelations]`,
  `#[DeleteWhenMissingModels]`.
- Pass models (they serialize as ids and are re-fetched) or scalar ids,
  never big arrays or closures. `#[WithoutRelations]` stops loaded
  relations from being serialized.
- `handle()` re-reads state and usually delegates to an action.
- Keep jobs small. Fan out with `Bus::batch([...])` (progress, then/catch)
  or `Bus::chain([...])` for ordered steps.

## Idempotency, uniqueness, and debouncing

Jobs run **at least once**: after a timeout, a worker crash, or a deploy,
the same job runs again.
- Guard with state checks (`reminded_at`, `status`), unique database keys
  (`upsert` on a provider event id), or idempotency keys sent to APIs that
  support them (Stripe).
- `ShouldBeUnique` + `uniqueId()` prevents duplicate *queued* copies
  (`ShouldBeUniqueUntilProcessing` releases the lock when it starts). It
  needs a cache store with atomic locks, which the database store has.
- `#[DebounceFor(30)]` runs only the latest of many dispatches in the
  window. It's the right tool for "reindex this product" storms.

## After commit

A job dispatched inside a transaction can run **before the commit**, see
missing rows, or run for a write that later rolled back.
- Events fired in transactions: implement `ShouldDispatchAfterCommit`.
- Jobs and queued listeners: implement `ShouldQueueAfterCommit`, or chain
  `->afterCommit()` on dispatch.
- Or set `'after_commit' => true` on the queue connection in
  `config/queue.php` as the app-wide default.
- `scripts/laravel_audit.php` flags dispatches inside `DB::transaction`
  whose class doesn't opt in.

## Failures, retries, and timeouts

- Set `#[Timeout]` below the worker's `--timeout`, and keep the
  connection's `retry_after` above both, or a slow job runs twice at once.
- Throw to retry. Call `$this->fail($e)` for permanent errors (a 4xx from an
  API) so you don't burn retries.
- `failed(Throwable $e)` notifies or compensates. Failed jobs go to
  `failed_jobs`: inspect with `queue:failed`, and replay with `queue:retry`.
- Rate-limit external APIs with job middleware:
  `new RateLimited('stripe')`, `WithoutOverlapping($key)`, and
  `ThrottlesExceptions`.

## Drivers: database first, then Redis + Horizon

- **Database queue** (the skeleton default): no extra infrastructure,
  transactional with your data, and fine for thousands of jobs per minute
  on Postgres.
- **Redis + Horizon** when volume or latency demands it, or when you want
  Horizon's dashboard, auto-balancing, and per-queue metrics. Horizon
  requires Redis (not Redis Cluster). Run `php artisan horizon` as the
  worker command, and gate `/horizon` with `Gate::define('viewHorizon')`.
- `QUEUE_CONNECTION=sync` is for tests only; in production it runs jobs
  inside the request.
- The `failover` connection lists fallback connections, for when the primary
  queue backend is down.
- SQS for serverless setups; Laravel Cloud manages queue clusters for you.

## Routing jobs to queues

Use queues by **latency class**, not by job type: `high` (user is waiting:
password reset, 2FA), `default`, and `low` (reports, reindexing). Laravel 13
routes centrally:

```php
// AppServiceProvider::boot()
Queue::route(SendPasswordReset::class, queue: 'high');
Queue::route(LowPriority::class, queue: 'low');   // your own marker interface, trait, or parent class
```

Run workers with `--queue=high,default,low` so high always drains first.

## Workers in production

- A dedicated worker role/container:
  `php artisan queue:work --queue=high,default,low --tries=3 --max-time=3600`.
  `--max-time` (or `--max-jobs`) recycles workers to shed leaked memory.
- Workers hold the code in memory: deploys restart the containers (Kamal
  does), and on VMs run `php artisan queue:restart` after every deploy.
- On stop (SIGTERM), the worker finishes the current job, then exits. Kamal
  gives non-proxied roles its `drain_timeout` (30 s by default), so long
  jobs should checkpoint or be chunked.
- Scale by adding worker containers, not threads. Watch queue depth and
  wait time (Horizon, Pulse, or Nightwatch).

## Scheduling

- Define tasks in `routes/console.php` with the `Schedule` facade:
  `Schedule::job(new SendReminders)->dailyAt('08:00')->onOneServer()->withoutOverlapping();`
- Run **one** scheduler: a scheduler role running
  `php artisan schedule:work` (or cron `* * * * * php artisan schedule:run`).
  `onOneServer()` protects you if more than one runs anyway, using an
  atomic cache lock (database or Redis store).
- Scheduled tasks dispatch jobs. They don't do heavy work inline.
- `php artisan schedule:list` in CI or a runbook to see what runs when.

## Notifications and mail

- Queue them (`implements ShouldQueue` on the notification or mailable).
- Use Markdown mailables for consistent templates. Preview in the browser
  during development with a route returning the mailable.
- On-demand recipients: `Notification::route('mail', $email)->notify(...)`.
- Use a real provider in production (Postmark, SES, or Resend) with SPF,
  DKIM, and DMARC set up. Use `MAIL_MAILER=log` locally, or Mailpit.
- Test with `Notification::fake()` / `Mail::fake()` and
  `assertSentOnDemand`, `assertQueued`.

## Real-time with Reverb

- Reverb is the first-party WebSocket server (Pusher protocol). Install
  with `php artisan install:broadcasting`, and run
  `php artisan reverb:start` as its own role/container behind the proxy,
  with WebSocket upgrades allowed.
- Events implement `ShouldBroadcast` (queued) or `ShouldBroadcastNow`, and
  authorize private channels in `routes/channels.php` with the same tenant
  rules as policies.
- On the client, use Laravel Echo (`@laravel/echo-react` / `-vue` hooks,
  or Livewire listeners such as `#[On('echo:orders,OrderShipped')]`, and
  `echo-private:` for private channels).
- Scale Reverb horizontally with Redis pub/sub (`REVERB_SCALING_ENABLED`).
- Livewire polling (`wire:poll.10s`) is often enough; add Reverb when
  latency or load says so.

## Small async work without a job

- `defer(fn () => ...)` runs a closure after the response is sent, in the
  same process. It's good for metrics and cache warming, but it has no
  retries: use a job for anything that must happen.
- `Concurrency::run([fn () => ..., fn () => ...])` runs independent tasks in
  parallel child processes (for example, several slow API reads for one
  page).
