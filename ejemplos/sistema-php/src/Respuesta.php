<?php
declare(strict_types=1);

namespace Ejemplo;

/** Respuesta HTTP mínima; en CI4 sería `$this->response->setStatusCode()->setJSON()`. */
final class Respuesta
{
    public function __construct(public readonly int $estado, public readonly array $cuerpo)
    {
    }

    public static function json(array $cuerpo, int $estado = 200): self
    {
        return new self($estado, $cuerpo);
    }

    /** Error HTTP de autenticación/autorización (401/403), distinto de un error de negocio. */
    public static function http(int $estado, string $detalle): self
    {
        return new self($estado, ['ok' => false, 'detalle' => $detalle]);
    }
}
