<?php

use App\Http\Controllers\AvatarController;
use App\Http\Controllers\InvoiceController;
use Illuminate\Support\Facades\Route;

Route::middleware('auth')->group(function () {
    Route::get('/invoices/search', [InvoiceController::class, 'search']);
    Route::get('/invoices/export', [InvoiceController::class, 'export']);
    Route::post('/invoices/{id}/paid', [InvoiceController::class, 'markPaid']);
    Route::resource('invoices', InvoiceController::class)->only(['index', 'store', 'show']);
    Route::post('/avatar', [AvatarController::class, 'store']);
});
