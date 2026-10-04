<?php
declare(strict_types=1);

namespace Ejemplo\Tools;

use Ejemplo\Datos\Repositorio;

final class ResumenEstablecimiento implements Herramienta
{
    public function __construct(private readonly Repositorio $repo)
    {
    }

    public function nombre(): string
    {
        return 'resumen_establecimiento';
    }

    public function definicion(): array
    {
        return [
            'nombre' => $this->nombre(),
            'descripcion' => 'Devuelve la superficie en hectáreas y el cultivo de un establecimiento a partir de su id '
                . '(obtenido con listar_establecimientos). Si el id no existe o no es del usuario, responde no_encontrado.',
            'parametros' => [
                'type' => 'object',
                'properties' => [
                    'id' => ['type' => 'string', 'description' => 'id del establecimiento (obtenido con listar_establecimientos)'],
                ],
                'required' => ['id'],
                'additionalProperties' => false,
            ],
            'efecto' => 'lectura',
            'timeout_s' => 15,
        ];
    }

    public function ejecutar(array $parametros, string $usuarioId): array
    {
        $id = $parametros['id'] ?? null;
        if (!is_string($id)) {
            return Resultado::error('parametros_invalidos', '`id` debe ser string');
        }
        foreach ($this->repo->establecimientosDe($usuarioId) as $e) {
            if ($e['id'] === $id) {
                return Resultado::ok($e, 'establecimientos');
            }
        }
        // Mismo mensaje para "no existe" y "es de otro usuario": no se revela cuál.
        return Resultado::error('no_encontrado', 'No existe o no tenés acceso');
    }
}
