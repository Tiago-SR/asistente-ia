<?php
declare(strict_types=1);

namespace Ejemplo\Tools;

use Ejemplo\Datos\Repositorio;

final class ResumenPorCultivo implements Herramienta
{
    public function __construct(private readonly Repositorio $repo)
    {
    }

    public function nombre(): string
    {
        return 'resumen_por_cultivo';
    }

    public function definicion(): array
    {
        return [
            'nombre' => $this->nombre(),
            'descripcion' => 'Suma la superficie en hectáreas de los establecimientos del usuario agrupada por cultivo, '
                . 'con la cantidad de establecimientos de cada uno y el total general. Usar para preguntas como '
                . '"¿cuántas hectáreas de soja tengo?"; para ver un establecimiento concreto usar resumen_establecimiento. '
                . 'No devuelve geometrías ni la lista de establecimientos.',
            'parametros' => [
                'type' => 'object',
                'properties' => new \stdClass(),
                'additionalProperties' => false,
            ],
            'efecto' => 'lectura',
            'timeout_s' => 15,
        ];
    }

    public function ejecutar(array $parametros, string $usuarioId): array
    {
        $porCultivo = [];
        foreach ($this->repo->establecimientosDe($usuarioId) as $e) {   // solo los del usuario
            $c = $e['cultivo'];
            $porCultivo[$c] ??= ['cultivo' => $c, 'superficie_ha' => 0.0, 'establecimientos' => 0];
            $porCultivo[$c]['superficie_ha'] += $e['superficie_ha'];
            $porCultivo[$c]['establecimientos']++;
        }
        $filas = array_values(array_map(
            fn(array $f) => ['superficie_ha' => round($f['superficie_ha'], 1)] + $f,
            $porCultivo,
        ));
        usort($filas, fn($a, $b) => $b['superficie_ha'] <=> $a['superficie_ha']);
        return Resultado::ok([
            'por_cultivo' => $filas,
            'superficie_total_ha' => round(array_sum(array_column($filas, 'superficie_ha')), 1),
        ], 'establecimientos');
    }
}
