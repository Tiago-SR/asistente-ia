<?php
declare(strict_types=1);

namespace Ejemplo\Tools;

/**
 * Tool de ESCRITURA de ejemplo, solo para demostrar la capa de solo lectura: aparece en el manifiesto
 * (efecto "escritura") y el controlador la rechaza con 403 si llega con scope de lectura.
 * Aunque se ejecutara, no hace nada: no hay nada que borrar.
 */
final class EliminarEstablecimiento implements Herramienta
{
    public function nombre(): string
    {
        return 'eliminar_establecimiento';
    }

    public function definicion(): array
    {
        return [
            'nombre' => $this->nombre(),
            'descripcion' => 'Elimina un establecimiento por su id (obtenido con listar_establecimientos). '
                . 'Es una tool de escritura: el asistente no la ofrece al modelo y el sistema la rechaza con scope de lectura.',
            'parametros' => [
                'type' => 'object',
                'properties' => [
                    'id' => ['type' => 'string', 'description' => 'id del establecimiento (obtenido con listar_establecimientos)'],
                ],
                'required' => ['id'],
                'additionalProperties' => false,
            ],
            'efecto' => 'escritura',
            'timeout_s' => 15,
        ];
    }

    public function ejecutar(array $parametros, string $usuarioId): array
    {
        return Resultado::error('no_disponible', 'tool de ejemplo: no realiza ninguna acción');
    }
}
