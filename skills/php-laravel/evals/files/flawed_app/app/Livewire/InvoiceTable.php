<?php

namespace App\Livewire;

use App\Models\Invoice;
use Livewire\Component;

class InvoiceTable extends Component
{
    public int $accountId;

    public function mount(): void
    {
        $this->accountId = auth()->user()->account_id;
    }

    public function delete(int $id): void
    {
        Invoice::find($id)->delete();
    }

    public function render()
    {
        return view('livewire.invoice-table', [
            'invoices' => Invoice::where('account_id', $this->accountId)->get(),
        ]);
    }
}
