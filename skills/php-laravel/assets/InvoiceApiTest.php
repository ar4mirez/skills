<?php

declare(strict_types=1);

use App\Enums\InvoiceStatus;
use App\Events\InvoicePaid;
use App\Models\Invoice;
use App\Models\User;
use Illuminate\Support\Facades\Event;
use Laravel\Sanctum\Sanctum;

use function Pest\Laravel\getJson;
use function Pest\Laravel\postJson;

it('rejects guests', function (): void {
    getJson('/api/invoices')->assertUnauthorized();
});

it('lists only invoices from the current account', function (): void {
    $user = User::factory()->create();
    Invoice::factory()->for($user->account)->count(2)->create();
    Invoice::factory()->create(); // another account

    Sanctum::actingAs($user);

    getJson('/api/invoices')
        ->assertOk()
        ->assertJsonCount(2, 'data');
});

it('creates an invoice with a sequential number', function (): void {
    Sanctum::actingAs(User::factory()->create());

    postJson('/api/invoices', [
        'customer_email' => 'ada@example.com',
        'amount_cents' => 12_500,
        'due_on' => now()->addWeek()->toDateString(),
    ])
        ->assertCreated()
        ->assertJsonPath('data.number', 'INV-00001')
        ->assertJsonPath('data.status', 'draft');
});

it('validates the payload', function (array $payload, string $field): void {
    Sanctum::actingAs(User::factory()->create());

    postJson('/api/invoices', $payload)->assertUnprocessable()->assertJsonValidationErrors($field);
})->with([
    'missing email' => [['amount_cents' => 100, 'due_on' => '2099-01-01'], 'customer_email'],
    'zero amount' => [['customer_email' => 'a@b.co', 'amount_cents' => 0, 'due_on' => '2099-01-01'], 'amount_cents'],
    'past due date' => [['customer_email' => 'a@b.co', 'amount_cents' => 100, 'due_on' => '2000-01-01'], 'due_on'],
]);

it('forbids reading another account\'s invoice', function (): void {
    Sanctum::actingAs(User::factory()->create());

    getJson('/api/invoices/'.Invoice::factory()->create()->id)->assertForbidden();
});

it('records a full payment and dispatches InvoicePaid', function (): void {
    Event::fake([InvoicePaid::class]);
    $user = User::factory()->create();
    $invoice = Invoice::factory()->for($user->account)->sent()->create(['amount_cents' => 5_000]);

    Sanctum::actingAs($user);

    postJson("/api/invoices/{$invoice->id}/payments", ['amount_cents' => 5_000])
        ->assertOk()
        ->assertJsonPath('data.status', 'paid');

    expect($invoice->refresh()->status)->toBe(InvoiceStatus::Paid);
    Event::assertDispatched(InvoicePaid::class);
});

it('refuses partial payments', function (): void {
    $user = User::factory()->create();
    $invoice = Invoice::factory()->for($user->account)->sent()->create(['amount_cents' => 5_000]);

    Sanctum::actingAs($user);

    postJson("/api/invoices/{$invoice->id}/payments", ['amount_cents' => 100])
        ->assertUnprocessable()
        ->assertJsonPath('message', 'Invoice cannot be paid: partial payments are not supported.');
});
