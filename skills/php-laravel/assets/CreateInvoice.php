<?php

declare(strict_types=1);

namespace App\Actions\Billing;

use App\Data\InvoiceData;
use App\Models\Account;
use App\Models\Invoice;
use Illuminate\Support\Facades\DB;

final readonly class CreateInvoice
{
    public function handle(Account $account, InvoiceData $data): Invoice
    {
        return DB::transaction(function () use ($account, $data): Invoice {
            // Lock the parent row: Postgres rejects FOR UPDATE on an aggregate.
            Account::query()->lockForUpdate()->findOrFail($account->id);
            $next = $account->invoices()->count() + 1;

            return $account->invoices()->create([
                'number' => sprintf('INV-%05d', $next),
                'customer_email' => $data->customerEmail,
                'amount_cents' => $data->amountCents,
                'currency' => $data->currency,
                'due_on' => $data->dueOn,
            ]);
        });
    }
}
