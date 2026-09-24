<?php

declare(strict_types=1);

use App\Jobs\SendInvoiceReminder;
use App\Models\Invoice;
use App\Notifications\InvoiceReminder;
use Illuminate\Notifications\AnonymousNotifiable;
use Illuminate\Support\Facades\Notification;

it('reminds an overdue invoice exactly once', function (): void {
    Notification::fake();
    $invoice = Invoice::factory()->overdue()->create();

    dispatch_sync(new SendInvoiceReminder($invoice));
    dispatch_sync(new SendInvoiceReminder($invoice)); // a retry must be a no-op

    Notification::assertSentOnDemandTimes(InvoiceReminder::class, 1);
    Notification::assertSentOnDemand(
        InvoiceReminder::class,
        fn (InvoiceReminder $notification, array $channels, AnonymousNotifiable $notifiable): bool => $notifiable->routes['mail'] === $invoice->customer_email,
    );
    expect($invoice->refresh()->reminded_at)->not->toBeNull();
});

it('skips invoices that are not overdue', function (): void {
    Notification::fake();

    dispatch_sync(new SendInvoiceReminder(Invoice::factory()->paid()->create()));

    Notification::assertNothingSent();
});
