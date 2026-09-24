<?php

declare(strict_types=1);

namespace App\Exceptions;

use DomainException;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Symfony\Component\HttpFoundation\Response;

final class InvoiceNotPayable extends DomainException
{
    public static function because(string $reason): self
    {
        return new self("Invoice cannot be paid: {$reason}.");
    }

    public function render(Request $request): JsonResponse|Response|false
    {
        if (! $request->expectsJson()) {
            return false;
        }

        return new JsonResponse(['message' => $this->getMessage()], Response::HTTP_UNPROCESSABLE_ENTITY);
    }
}
