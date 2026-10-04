<?php
declare(strict_types=1);

namespace Ejemplo\Auth;

use Ejemplo\Config;
use Firebase\JWT\JWT;

/** Emite el JWT de usuario de la sección 1 del contrato. */
final class EmisorToken
{
    public function __construct(private readonly Config $cfg)
    {
    }

    /** @param array{id: string, nombre: string} $usuario  usuario ya autenticado por el sistema */
    public function emitir(array $usuario, ?int $ahora = null): array
    {
        $ahora ??= time();
        $exp = $ahora + Config::VIDA_TOKEN_S;
        $claims = [
            'iss' => $this->cfg->id,
            'aud' => $this->cfg->audiencia,
            'sub' => $usuario['id'],
            'iat' => $ahora,
            'exp' => $exp,
            'jti' => bin2hex(random_bytes(16)),
            'scope' => 'asistente:lectura',
            'nombre' => $usuario['nombre'],
            'locale' => 'es-UY',
        ];
        return [
            'token' => JWT::encode($claims, $this->cfg->claveFirma, $this->cfg->alg),
            'expira' => gmdate('Y-m-d\TH:i:s\Z', $exp),
        ];
    }
}
