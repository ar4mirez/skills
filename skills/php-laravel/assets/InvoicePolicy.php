<?php

declare(strict_types=1);

namespace App\Policies;

use App\Models\Invoice;
use App\Models\User;

final class InvoicePolicy
{
    public function viewAny(User $user): bool
    {
        return $user->account_id !== null;
    }

    public function view(User $user, Invoice $invoice): bool
    {
        return $user->account_id === $invoice->account_id;
    }

    public function create(User $user): bool
    {
        return $user->account_id !== null;
    }

    public function pay(User $user, Invoice $invoice): bool
    {
        return $this->view($user, $invoice) && $invoice->status->isPayable();
    }
}
