<?php
declare(strict_types=1);

namespace Ejemplo\Tools;

use Ejemplo\Datos\Almacen;

final class ListarNotas implements Herramienta
{
    public function __construct(private readonly Almacen $almacen)
    {
    }

    public function nombre(): string
    {
        return 'listar_notas';
    }

    public function definicion(): array
    {
        return [
            'nombre' => $this->nombre(),
            'descripcion' => 'Lista las notas del usuario (id, establecimiento y texto). Usar antes de modificar una nota '
                . 'para obtener su id.',
            'parametros' => [
                'type' => 'object',
                'properties' => [
                    'establecimiento_id' => ['type' => 'string', 'description' => 'filtra por establecimiento'],
                ],
                'additionalProperties' => false,
            ],
            'efecto' => 'lectura',
            'timeout_s' => 15,
        ];
    }

    public function ejecutar(array $parametros, string $usuarioId): array
    {
        return Resultado::ok(['notas' => $this->almacen->notasDe($usuarioId, $parametros['establecimiento_id'] ?? null)], 'notas');
    }
}
