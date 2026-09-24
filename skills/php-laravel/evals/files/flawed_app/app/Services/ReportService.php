<?php

namespace App\Services;

use Illuminate\Support\Facades\Storage;

class ReportService
{
    private static array $cache = [];

    public function bucket(): string
    {
        return env('REPORT_BUCKET', 'reports');
    }

    public function forUser(int $userId): array
    {
        return self::$cache[$userId] ??= Storage::disk('s3')->files($this->bucket().'/'.$userId);
    }
}
