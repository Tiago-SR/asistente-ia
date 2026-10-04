<?php
declare(strict_types=1);

namespace Ejemplo\Auth;

use Ejemplo\Config;
use Firebase\JWT\JWT;
use Firebase\JWT\Key;

/**
 * Valida el JWT de usuario: firma con el algoritmo FIJO de la configuración (rechaza `none` y
 * confusión HS/RS), `iss`, `aud`, `exp` y claims obligatorios. El scope se comprueba aparte.
 */
final class ValidadorToken
{
    public function __construct(private readonly Config $cfg)
    {
    }

    /** @throws TokenInvalido */
    public function validar(string $token): array
    {
        try {
            $claims = (array) JWT::decode($token, new Key($this->cfg->claveVerif, $this->cfg->alg));
        } catch (\Throwable $e) { // firma, formato, alg, exp, nbf, iat…
            throw new TokenInvalido($e->getMessage(), 0, $e);
        }
        foreach (['iss', 'aud', 'sub', 'iat', 'exp', 'jti'] as $claim) {
            if (!isset($claims[$claim]) || $claims[$claim] === '') {
                throw new TokenInvalido("falta el claim $claim");
            }
        }
        if ($claims['iss'] !== $this->cfg->id) {
            throw new TokenInvalido('iss inválido');
        }
        $aud = (array) $claims['aud'];
        if (!in_array($this->cfg->audiencia, $aud, true)) {
            throw new TokenInvalido('aud inválido');
        }
        if (!is_string($claims['sub'])) {
            throw new TokenInvalido('sub debe ser string');
        }
        return $claims;
    }
}
