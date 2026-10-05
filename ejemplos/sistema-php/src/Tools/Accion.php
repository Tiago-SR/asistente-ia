<?php
declare(strict_types=1);

namespace Ejemplo\Tools;

/**
 * Tool de escritura con confirmación (sección 8 del contrato). El controlador llama a `preparar`
 * para la propuesta (sin efectos) y a `ejecutar` solo con un token de escritura válido.
 */
interface Accion extends Herramienta
{
    /**
     * Valida permisos y datos y redacta lo que el usuario confirmará, SIN escribir nada.
     * @return array{resumen: string, detalle: list<string>, version: ?int}|array{ok: false, error: string, detalle: string}
     *         `version`: la del registro que se modifica (null si se crea uno nuevo)
     */
    public function preparar(array $parametros, string $usuarioId): array;
}
