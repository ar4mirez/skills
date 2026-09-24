<?php

namespace Tests\Feature;

use App\Models\Invoice;
use Illuminate\Support\Facades\Http;
use Tests\TestCase;

class InvoiceTest extends TestCase
{
    public function test_index_loads(): void
    {
        Http::fake(['api.stripe.com/*' => Http::response(['ok' => true])]);

        $this->get('/invoices')->assertOk();
    }
}
