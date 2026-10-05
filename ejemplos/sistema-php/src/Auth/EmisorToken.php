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
        return $this->firmar($usuario, 'asistente:lectura', Config::VIDA_TOKEN_S, [], $ahora);
    }

    /**
     * Token de escritura (sección 8.3): corto, de un solo uso (`jti`) y atado a una tool, a la huella
     * de la propuesta y a la confirmación. Solo se llama tras comprobar que la huella es de una
     * propuesta vigente de este usuario.
     */
    public function emitirEscritura(array $usuario, string $tool, string $huella, string $cid, ?int $ahora = null): array
    {
        return $this->firmar($usuario, 'asistente:escritura', Config::VIDA_TOKEN_ESCRITURA_S,
            ['act' => $tool, 'ph' => $huella, 'cid' => $cid], $ahora);
    }

    private function firmar(array $usuario, string $scope, int $vida, array $extra, ?int $ahora): array
    {
        $ahora ??= time();
        $exp = $ahora + $vida;
        $claims = $extra + [
            'iss' => $this->cfg->id,
            'aud' => $this->cfg->audiencia,
            'sub' => $usuario['id'],
            'iat' => $ahora,
            'exp' => $exp,
            'jti' => bin2hex(random_bytes(16)),
            'scope' => $scope,
            'nombre' => $usuario['nombre'],
            'locale' => 'es-UY',
        ];
        return [
            'token' => JWT::encode($claims, $this->cfg->claveFirma, $this->cfg->alg),
            'expira' => gmdate('Y-m-d\TH:i:s\Z', $exp),
        ];
    }
}
