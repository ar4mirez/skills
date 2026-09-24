<?php

declare(strict_types=1);

namespace App\Models;

use App\Enums\InvoiceStatus;
use Carbon\CarbonImmutable;
use Database\Factories\InvoiceFactory;
use Illuminate\Database\Eloquent\Attributes\Fillable;
use Illuminate\Database\Eloquent\Attributes\Scope;
use Illuminate\Database\Eloquent\Builder;
use Illuminate\Database\Eloquent\Factories\HasFactory;
use Illuminate\Database\Eloquent\Model;
use Illuminate\Database\Eloquent\Relations\BelongsTo;
use Override;

/**
 * @property int $id
 * @property int $account_id
 * @property string $number
 * @property string $customer_email
 * @property InvoiceStatus $status
 * @property int $amount_cents
 * @property string $currency
 * @property CarbonImmutable $due_on
 * @property CarbonImmutable|null $paid_at
 * @property CarbonImmutable|null $reminded_at
 */
#[Fillable(['number', 'customer_email', 'amount_cents', 'currency', 'due_on'])]
final class Invoice extends Model
{
    /** @use HasFactory<InvoiceFactory> */
    use HasFactory;

    /** @var array<string, mixed> */
    #[Override]
    protected $attributes = [
        'status' => 'draft',
        'currency' => 'USD',
    ];

    /** @return BelongsTo<Account, $this> */
    public function account(): BelongsTo
    {
        return $this->belongsTo(Account::class);
    }

    public function isOverdue(): bool
    {
        return $this->status->isPayable() && $this->due_on->isPast();
    }

    /** @param Builder<self> $query */
    #[Scope]
    protected function overdue(Builder $query): void
    {
        $query->where('status', InvoiceStatus::Sent)->whereDate('due_on', '<', now());
    }

    /** @return array<string, string> */
    protected function casts(): array
    {
        return [
            'status' => InvoiceStatus::class,
            'amount_cents' => 'integer',
            'due_on' => 'immutable_date',
            'paid_at' => 'immutable_datetime',
            'reminded_at' => 'immutable_datetime',
        ];
    }
}
