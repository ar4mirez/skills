<?php

declare(strict_types=1);

namespace App\Jobs;

use App\Models\Invoice;
use App\Notifications\InvoiceReminder;
use Illuminate\Contracts\Queue\ShouldBeUnique;
use Illuminate\Contracts\Queue\ShouldQueue;
use Illuminate\Foundation\Queue\Queueable;
use Illuminate\Queue\Attributes\Backoff;
use Illuminate\Queue\Attributes\DeleteWhenMissingModels;
use Illuminate\Queue\Attributes\Tries;
use Illuminate\Support\Facades\Notification;

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
