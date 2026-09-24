<?php

declare(strict_types=1);

use App\Enums\InvoiceStatus;
use App\Models\Invoice;
use App\Models\User;
use Livewire\Livewire;

it('shows the account\'s invoices and filters by status', function (): void {
    $user = User::factory()->create();
    Invoice::factory()->for($user->account)->sent()->create(['number' => 'INV-00001']);
    Invoice::factory()->for($user->account)->paid()->create(['number' => 'INV-00002']);
    Invoice::factory()->create(['number' => 'INV-99999']);

    Livewire::actingAs($user)
        ->test('pages::invoices.index')
        ->assertSee('INV-00001')
        ->assertSee('INV-00002')
        ->assertDontSee('INV-99999')
        ->set('status', 'paid')
        ->assertDontSee('INV-00001')
        ->assertSee('INV-00002');
});

it('marks a sent invoice paid', function (): void {
    $user = User::factory()->create();
    $invoice = Invoice::factory()->for($user->account)->sent()->create();

    Livewire::actingAs($user)
        ->test('pages::invoices.index')
        ->call('markPaid', $invoice->id)
        ->assertOk();

    expect($invoice->refresh()->status)->toBe(InvoiceStatus::Paid);
});

it('forbids paying another account\'s invoice by tampering with the id', function (): void {
    $invoice = Invoice::factory()->sent()->create();

    Livewire::actingAs(User::factory()->create())
        ->test('pages::invoices.index')
        ->call('markPaid', $invoice->id)
        ->assertForbidden();

    expect($invoice->refresh()->status)->toBe(InvoiceStatus::Sent);
});

it('renders for a signed-in user', function (): void {
    $this->actingAs(User::factory()->create())->get('/invoices')->assertOk()->assertSee('Invoices');
});
