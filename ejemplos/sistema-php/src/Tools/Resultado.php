<?php
declare(strict_types=1);

namespace Ejemplo\Tools;

/** Construye el cuerpo `200` del contrato (sección 3). */
final class Resultado
{
    public static function ok(array $datos, string $fuente, array $ui = []): array
    {
        $r = ['ok' => true, 'datos' => $datos, 'fuente' => $fuente];
        return $ui ? $r + ['ui' => $ui] : $r;
    }

    /** @param string $error no_encontrado | sin_acceso | parametros_invalidos | no_disponible */
    public static function error(string $error, string $detalle): array
    {
        return ['ok' => false, 'error' => $error, 'detalle' => $detalle];
    }
}
