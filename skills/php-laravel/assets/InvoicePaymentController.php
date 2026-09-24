<?php

declare(strict_types=1);

namespace App\Http\Controllers\Api;

use App\Actions\Billing\RecordPayment;
use App\Http\Controllers\Controller;
use App\Http\Requests\Billing\RecordPaymentRequest;
use App\Http\Resources\InvoiceResource;
use App\Models\Invoice;

final class InvoicePaymentController extends Controller
{
    public function store(RecordPaymentRequest $request, Invoice $invoice, RecordPayment $recordPayment): InvoiceResource
    {
        return InvoiceResource::make($recordPayment->handle($invoice, $request->integer('amount_cents')));
    }
}
