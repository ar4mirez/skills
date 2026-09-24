<?php

namespace App\Http\Controllers;

use App\Jobs\SendReceipt;
use App\Models\Invoice;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;

class InvoiceController extends Controller
{
    public function index()
    {
        $invoices = Invoice::all();

        return view('invoices.index', compact('invoices'));
    }

    public function store(Request $request)
    {
        $request->validate([
            'customer_id' => 'required',
            'amount' => 'required|numeric',
        ]);

        $invoice = Invoice::create($request->all());

        return redirect()->route('invoices.show', $invoice);
    }

    public function show(Invoice $invoice)
    {
        return view('invoices.show', compact('invoice'));
    }

    public function markPaid(Request $request, $id)
    {
        $invoice = Invoice::findOrFail($id);

        DB::transaction(function () use ($invoice) {
            $invoice->update(['status' => 'paid', 'paid_at' => now()]);
            SendReceipt::dispatch($invoice);
        });

        dd($invoice);

        return back();
    }

    public function search(Request $request)
    {
        $q = $request->input('q');
        $invoices = Invoice::whereRaw("customer_email like '%$q%'")->get();

        return view('invoices.index', compact('invoices'));
    }

    public function export(Request $request)
    {
        // ... build the CSV ...
        return redirect($request->input('next'));
    }
}
