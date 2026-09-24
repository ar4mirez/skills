<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Actions\Billing\CreateInvoice;
use App\Http\Controllers\Controller;
use App\Http\Requests\Billing\StoreInvoiceRequest;
use App\Http\Resources\InvoiceResource;
use App\Models\Invoice;
use App\Models\User;
use Illuminate\Container\Attributes\CurrentUser;
use Illuminate\Http\Resources\Json\AnonymousResourceCollection;
use Illuminate\Support\Facades\Gate;

final class InvoiceController extends Controller
{
    public function index(#[CurrentUser] User $user): AnonymousResourceCollection
    {
        Gate::authorize('viewAny', Invoice::class);

        $invoices = Invoice::query()
            ->where('account_id', $user->account_id)
            ->latest('due_on')
            ->cursorPaginate(25);

        return InvoiceResource::collection($invoices);
    }

    public function store(StoreInvoiceRequest $request, #[CurrentUser] User $user, CreateInvoice $createInvoice): InvoiceResource
    {
        $invoice = $createInvoice->handle($user->account()->firstOrFail(), $request->toData());

        return InvoiceResource::make($invoice);
    }

    public function show(Invoice $invoice): InvoiceResource
    {
        Gate::authorize('view', $invoice);

        return InvoiceResource::make($invoice);
    }
}
