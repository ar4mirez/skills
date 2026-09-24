# syntax=docker/dockerfile:1
# Production image: FrankenPHP + Octane, PHP 8.5, non-root, assets prebuilt.
ARG PHP_IMAGE=dunglas/frankenphp:1.12-php8.5-alpine

# 1. PHP dependencies (no dev), without running scripts that need the app.
FROM ${PHP_IMAGE} AS vendor
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer
RUN install-php-extensions intl pcntl pdo_pgsql zip
WORKDIR /app
COPY composer.json composer.lock ./
RUN composer install --no-dev --no-interaction --no-progress --no-scripts --no-autoloader --prefer-dist

# 2. Frontend assets.
FROM node:24-alpine AS assets
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# 3. Runtime.
FROM ${PHP_IMAGE} AS runtime
RUN install-php-extensions intl opcache pcntl pdo_pgsql zip \
 && cp "$PHP_INI_DIR/php.ini-production" "$PHP_INI_DIR/php.ini"
COPY docker/php.ini "$PHP_INI_DIR/conf.d/zz-app.ini"
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer

ARG UID=1000
RUN adduser -D -u ${UID} app \
 && mkdir -p /data/caddy /config/caddy \
 && chown -R app:app /data /config

WORKDIR /app
COPY --chown=app:app --from=vendor /app/vendor ./vendor
COPY --chown=app:app . .
COPY --chown=app:app --from=assets /app/public/build ./public/build
RUN composer dump-autoload --classmap-authoritative --no-dev \
 && rm /usr/bin/composer \
 && chown -R app:app storage bootstrap/cache

USER app
ENV APP_ENV=production APP_DEBUG=false LOG_CHANNEL=stderr OCTANE_SERVER=frankenphp
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s CMD wget -qO- http://127.0.0.1:8080/up >/dev/null || exit 1
ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["php", "artisan", "octane:frankenphp", "--host=0.0.0.0", "--port=8080", "--admin-port=2019", "--max-requests=1000"]
