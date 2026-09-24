<?php

declare(strict_types=1);

use Illuminate\Support\Facades\DB;

arch()->preset()->php();
arch()->preset()->security();
arch()->preset()->laravel();

arch('app code is strictly typed')
    ->expect('App')
    ->toUseStrictTypes();

arch('actions are final, readonly, and expose handle()')
    ->expect('App\Actions')
    ->toBeFinal()
    ->toBeReadonly()
    ->toHaveMethod('handle');

arch('controllers stay thin: no direct DB facade or query building')
    ->expect('App\Http\Controllers')
    ->not->toUse([DB::class]);

arch('models are only touched by the HTTP layer through actions, resources, and queries')
    ->expect('App\Models')
    ->not->toUse(['App\Http']);

arch('no debugging leftovers')
    ->expect(['dd', 'dump', 'ray', 'var_dump', 'die'])
    ->not->toBeUsed();
