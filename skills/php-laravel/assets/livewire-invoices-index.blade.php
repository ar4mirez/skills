<?php // resources/views/pages/invoices/⚡index.blade.php

use App\Actions\Billing\RecordPayment;
use App\Enums\InvoiceStatus;
use App\Models\Invoice;
use Illuminate\Pagination\LengthAwarePaginator;
use Livewire\Attributes\Computed;
use Livewire\Attributes\Title;
use Livewire\Attributes\Url;
use Livewire\Component;
use Livewire\WithPagination;

new #[Title('Invoices')] class extends Component
{
    use WithPagination;

    #[Url]
    public string $status = '';

    /** @return LengthAwarePaginator<int, Invoice> */
    #[Computed]
    public function invoices(): LengthAwarePaginator
    {
        $this->authorize('viewAny', Invoice::class);

        return Invoice::query()
            ->where('account_id', auth()->user()?->account_id)
            ->when(InvoiceStatus::tryFrom($this->status), fn ($query, InvoiceStatus $status) => $query->where('status', $status))
            ->latest('due_on')
            ->paginate(20);
    }

    public function updatedStatus(): void
    {
        $this->resetPage();
    }

    // Never trust $id from the browser: re-query and authorize before acting.
    public function markPaid(int $id, RecordPayment $recordPayment): void
    {
        $invoice = Invoice::query()->findOrFail($id);
        $this->authorize('pay', $invoice);

        $recordPayment->handle($invoice, $invoice->amount_cents);

        unset($this->invoices);
    }
};
?>

<div class="space-y-4">
    <div class="flex items-center justify-between">
        <h1 class="text-2xl font-semibold">Invoices</h1>
        <select wire:model.live="status" class="rounded border-zinc-300">
            <option value="">All</option>
            @foreach (InvoiceStatus::cases() as $case)
                <option value="{{ $case->value }}">{{ $case->label() }}</option>
            @endforeach
        </select>
    </div>

    <table class="w-full text-left text-sm">
        <thead>
            <tr><th>Number</th><th>Customer</th><th>Due</th><th>Status</th><th></th></tr>
        </thead>
        <tbody>
            @forelse ($this->invoices as $invoice)
                <tr wire:key="invoice-{{ $invoice->id }}">
                    <td>{{ $invoice->number }}</td>
                    <td>{{ $invoice->customer_email }}</td>
                    <td>{{ $invoice->due_on->toDateString() }}</td>
                    <td>{{ $invoice->status->label() }}</td>
                    <td>
                        @can('pay', $invoice)
                            <button wire:click="markPaid({{ $invoice->id }})" wire:confirm="Mark {{ $invoice->number }} as paid?">Mark paid</button>
                        @endcan
                    </td>
                </tr>
            @empty
                <tr><td colspan="5">No invoices yet.</td></tr>
            @endforelse
        </tbody>
    </table>

    {{ $this->invoices->links() }}
</div>
