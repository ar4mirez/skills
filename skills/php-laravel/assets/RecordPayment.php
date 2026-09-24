<?php

declare(strict_types=1);

namespace App\Actions\Billing;

use App\Enums\InvoiceStatus;
use App\Events\InvoicePaid;
use App\Exceptions\InvoiceNotPayable;
use App\Models\Invoice;
use Illuminate\Support\Facades\DB;

final readonly class RecordPayment
{
    public function handle(Invoice $invoice, int $amountCents): Invoice
    {
        return DB::transaction(function () use ($invoice, $amountCents): Invoice {
            $invoice = Invoice::query()->lockForUpdate()->findOrFail($invoice->id);

            if (! $invoice->status->isPayable()) {
                throw InvoiceNotPayable::because("invoice {$invoice->number} is {$invoice->status->value}");
            }

            if ($amountCents !== $invoice->amount_cents) {
                throw InvoiceNotPayable::because('partial payments are not supported');
            }

            $invoice->forceFill(['status' => InvoiceStatus::Paid, 'paid_at' => now()])->save();

            event(new InvoicePaid($invoice));

            return $invoice;
        });
    }
}
