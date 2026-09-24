<?php

declare(strict_types=1);

namespace App\Enums;

enum InvoiceStatus: string
{
    case Draft = 'draft';
    case Sent = 'sent';
    case Paid = 'paid';
    case Void = 'void';

    public function isPayable(): bool
    {
        return $this === self::Sent;
    }

    public function label(): string
    {
        return ucfirst($this->value);
    }
}
