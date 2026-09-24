<?php

declare(strict_types=1);

use App\Http\Controllers\Api\InvoiceController;
use App\Http\Controllers\Api\InvoicePaymentController;
use Illuminate\Support\Facades\Route;

Route::name('api.')->middleware(['auth:sanctum', 'throttle:api'])->group(function (): void {
    Route::apiResource('invoices', InvoiceController::class)->only(['index', 'store', 'show']);
    Route::apiResource('invoices.payments', InvoicePaymentController::class)->only(['store']);
});
