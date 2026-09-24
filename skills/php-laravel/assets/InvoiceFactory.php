<?php

declare(strict_types=1);

namespace Database\Factories;

use App\Enums\InvoiceStatus;
use App\Models\Account;
use App\Models\Invoice;
use Illuminate\Database\Eloquent\Factories\Factory;

/** @extends Factory<Invoice> */
final class InvoiceFactory extends Factory
{
    /** @return array<string, mixed> */
    public function definition(): array
    {
        return [
            'account_id' => Account::factory(),
            'number' => 'INV-'.fake()->unique()->numerify('#####'),
            'customer_email' => fake()->safeEmail(),
            'status' => InvoiceStatus::Draft,
            'amount_cents' => fake()->numberBetween(1_000, 500_000),
            'currency' => 'USD',
            'due_on' => now()->addDays(30),
        ];
    }

    public function sent(): static
    {
        return $this->state(['status' => InvoiceStatus::Sent]);
    }

    public function overdue(): static
    {
        return $this->sent()->state(['due_on' => now()->subDays(5)]);
    }

    public function paid(): static
    {
        return $this->state(['status' => InvoiceStatus::Paid, 'paid_at' => now()]);
    }
}
