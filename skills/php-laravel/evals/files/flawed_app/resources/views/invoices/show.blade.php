<x-layout>
    <h1>Invoice {{ $invoice->number }}</h1>
    <div class="notes">{!! $invoice->notes !!}</div>
    <p>You searched for: {!! request('q') !!}</p>
    <p>Customer: {{ $invoice->customer->name }}</p>
</x-layout>
