<?php

declare(strict_types=1);

namespace App\Data;

use Carbon\CarbonImmutable;

final readonly class InvoiceData
{
    public function __construct(
        public string $customerEmail,
        public int $amountCents,
        public string $currency,
        public CarbonImmutable $dueOn,
    ) {}
}
