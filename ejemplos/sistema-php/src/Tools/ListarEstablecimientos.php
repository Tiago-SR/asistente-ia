<?php
declare(strict_types=1);

namespace Ejemplo\Tools;

use Ejemplo\Datos\Repositorio;

final class ListarEstablecimientos implements Herramienta
{
    public function __construct(private readonly Repositorio $repo)
    {
    }

    public function nombre(): string
    {
        return 'listar_establecimientos';
    }

    public function definicion(): array
    {
        return [
            'nombre' => $this->nombre(),
            'descripcion' => 'Lista los establecimientos que el usuario puede ver, con su superficie en hectáreas '
                . 'y su cultivo. Se puede filtrar por nombre. Usar primero para resolver nombres a ids. '
                . 'No devuelve geometrías.',
            'parametros' => [
                'type' => 'object',
                'properties' => [
                    'texto' => ['type' => 'string', 'description' => 'filtro por nombre (contiene, sin distinguir mayúsculas ni tildes)'],
                ],
                'additionalProperties' => false,
            ],
            'efecto' => 'lectura',
            'timeout_s' => 15,
        ];
    }

    public function ejecutar(array $parametros, string $usuarioId): array
    {
        $texto = Texto::normalizar((string) ($parametros['texto'] ?? ''));
        $res = array_values(array_filter(
            $this->repo->establecimientosDe($usuarioId),   // solo los del usuario
            fn(array $e) => str_contains(Texto::normalizar($e['nombre']), $texto),
        ));
        $ui = array_map(fn(array $e) => [
            'tipo' => 'navegar', 'url' => '/establecimientos/' . $e['id'], 'etiqueta' => $e['nombre'],
        ], $res);
        return Resultado::ok(['establecimientos' => $res], 'establecimientos', $ui);
    }
}
