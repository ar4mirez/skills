<?php

declare(strict_types=1);

use Rector\Config\RectorConfig;
use RectorLaravel\Set\LaravelSetList;

return RectorConfig::configure()
    ->withPaths([__DIR__.'/app', __DIR__.'/config', __DIR__.'/database', __DIR__.'/routes', __DIR__.'/tests'])
    ->withPhpSets()
    ->withComposerBased(laravel: true)
    ->withSets([LaravelSetList::LARAVEL_CODE_QUALITY, LaravelSetList::LARAVEL_COLLECTION])
    ->withPreparedSets(deadCode: true, codeQuality: true, typeDeclarations: true, earlyReturn: true)
    ->withImportNames(removeUnusedImports: true);
