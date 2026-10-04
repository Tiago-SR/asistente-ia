<?php
declare(strict_types=1);

namespace Ejemplo;

/**
 * Configuración desde variables de entorno. En CI4: .env / app/Config.
 *
 *   SISTEMA_ID                id del sistema (claim `iss`; igual al `id` del registro del asistente)
 *   SISTEMA_NOMBRE            nombre en el manifiesto
 *   SISTEMA_AUDIENCIA         claim `aud`                                  [asistente]
 *   SISTEMA_ALG               HS256 | RS256                                [HS256]
 *   SISTEMA_SECRETO           clave de firma HS256 (mín. 32 caracteres)
 *   SISTEMA_CLAVE_PRIVADA     PEM de la clave privada RS256 (o SISTEMA_CLAVE_PRIVADA_ARCHIVO)
 *   SISTEMA_TOKEN_MANIFIESTO  credencial con la que el asistente lee el manifiesto
 *   APP_ENV                   `local` habilita ?usuario=ana en /asistente/token
 *   ASISTENTE_URL             URL pública del asistente (solo para la página de demostración)
 */
final class Config
{
    public const VIDA_TOKEN_S = 600; // contrato: 5–15 min

    public function __construct(
        public readonly string $id,
        public readonly string $nombre,
        public readonly string $audiencia,
        public readonly string $alg,
        public readonly string $claveFirma,   // secreto (HS256) o PEM privada (RS256)
        public readonly string $claveVerif,   // secreto (HS256) o PEM pública (RS256)
        public readonly string $tokenManifiesto,
        public readonly bool $local,
        public readonly string $asistenteUrl,
    ) {
    }

    public static function desdeEntorno(): self
    {
        $alg = self::env('SISTEMA_ALG', 'HS256');
        if (!in_array($alg, ['HS256', 'RS256'], true)) {
            throw new \RuntimeException('SISTEMA_ALG debe ser HS256 o RS256');
        }
        if ($alg === 'HS256') {
            $firma = $verif = self::requerida('SISTEMA_SECRETO');
        } else {
            $firma = getenv('SISTEMA_CLAVE_PRIVADA') ?: '';
            if ($firma === '' && ($archivo = getenv('SISTEMA_CLAVE_PRIVADA_ARCHIVO'))) {
                $firma = (string) @file_get_contents($archivo);
            }
            if ($firma === '') {
                throw new \RuntimeException('Falta SISTEMA_CLAVE_PRIVADA (o _ARCHIVO)');
            }
            $detalles = openssl_pkey_get_details(openssl_pkey_get_private($firma) ?: throw new \RuntimeException('clave privada ilegible'));
            $verif = $detalles['key'];
        }
        return new self(
            self::requerida('SISTEMA_ID'),
            self::env('SISTEMA_NOMBRE', 'Sistema PHP'),
            self::env('SISTEMA_AUDIENCIA', 'asistente'),
            $alg,
            $firma,
            $verif,
            self::requerida('SISTEMA_TOKEN_MANIFIESTO'),
            self::env('APP_ENV', 'production') === 'local',
            self::env('ASISTENTE_URL', 'http://localhost:8100'),
        );
    }

    private static function env(string $nombre, string $defecto): string
    {
        $v = getenv($nombre);
        return $v === false || $v === '' ? $defecto : $v;
    }

    private static function requerida(string $nombre): string
    {
        $v = getenv($nombre);
        if ($v === false || $v === '') {
            throw new \RuntimeException("Falta la variable de entorno $nombre");
        }
        return $v;
    }
}
