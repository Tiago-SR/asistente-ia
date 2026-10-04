FROM composer:2 AS deps
WORKDIR /app
COPY composer.json ./
RUN composer install --no-dev --no-progress --prefer-dist --optimize-autoloader

FROM composer:2 AS deps-dev
WORKDIR /app
COPY composer.json ./
RUN composer install --no-progress --prefer-dist

# Tests: docker build --target test -t sistema-php-test . && docker run --rm sistema-php-test
FROM php:8.3-cli-alpine AS test
WORKDIR /app
COPY --from=deps-dev /app/vendor ./vendor
COPY composer.json phpunit.xml ./
COPY src ./src
COPY tests ./tests
CMD ["vendor/bin/phpunit", "--colors=never"]

FROM php:8.3-cli-alpine
WORKDIR /app
COPY --from=deps /app/vendor ./vendor
COPY composer.json ./
COPY src ./src
COPY public ./public
USER nobody
EXPOSE 8000
CMD ["php", "-S", "0.0.0.0:8000", "-t", "public", "public/index.php"]
