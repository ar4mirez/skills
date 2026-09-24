<?php

declare(strict_types=1);

namespace App\Http\Requests\Billing;

use App\Data\InvoiceData;
use App\Models\Invoice;
use Illuminate\Contracts\Validation\ValidationRule;
use Illuminate\Foundation\Http\FormRequest;

final class StoreInvoiceRequest extends FormRequest
{
    public function authorize(): bool
    {
        return $this->user()?->can('create', Invoice::class) ?? false;
    }

    /** @return array<string, ValidationRule|array<mixed>|string> */
    public function rules(): array
    {
        return [
            'customer_email' => ['required', 'email:strict', 'max:255'],
            'amount_cents' => ['required', 'integer', 'min:1', 'max:100000000'],
            'currency' => ['sometimes', 'string', 'size:3', 'in:USD,EUR,GBP'],
            'due_on' => ['required', 'date', 'after_or_equal:today'],
        ];
    }

    public function toData(): InvoiceData
    {
        return new InvoiceData(
            customerEmail: $this->string('customer_email')->toString(),
            amountCents: $this->integer('amount_cents'),
            currency: $this->string('currency', 'USD')->upper()->toString(),
            dueOn: $this->date('due_on')?->toImmutable() ?? now()->toImmutable(),
        );
    }
}
