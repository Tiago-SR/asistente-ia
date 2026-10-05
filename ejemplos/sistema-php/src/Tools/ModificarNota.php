<?php
declare(strict_types=1);

namespace Ejemplo\Tools;

use Ejemplo\Config;
use Ejemplo\Datos\Almacen;
use Ejemplo\Datos\Repositorio;

final class ModificarNota implements Accion
{
    public function __construct(private readonly Repositorio $repo, private readonly Almacen $almacen)
    {
    }

    public function nombre(): string
    {
        return 'modificar_nota';
    }

    public function definicion(): array
    {
        return [
            'nombre' => $this->nombre(),
            'descripcion' => 'Reemplaza el texto de una nota existente del usuario. El usuario debe confirmarlo en '
                . 'pantalla. Obtener antes el id con listar_notas.',
            'parametros' => [
                'type' => 'object',
                'properties' => [
                    'nota_id' => ['type' => 'string', 'description' => 'id de la nota'],
                    'texto' => ['type' => 'string', 'description' => 'texto de la nota, solo lo que dijo el usuario', 'minLength' => 1, 'maxLength' => 500],
                ],
                'required' => ['nota_id', 'texto'],
                'additionalProperties' => false,
            ],
            'efecto' => 'escritura',
            'confirmacion' => ['ttl_s' => Config::TTL_PROPUESTA_S],
            'timeout_s' => 15,
        ];
    }

    public function preparar(array $parametros, string $usuarioId): array
    {
        $nota = $this->almacen->nota($usuarioId, $parametros['nota_id']);
        if ($nota === null) {
            return Resultado::error('no_encontrado', 'No existe o no tenés acceso');
        }
        $donde = '';
        foreach ($this->repo->establecimientosDe($usuarioId) as $e) {
            $donde = $e['id'] === $nota['establecimiento_id'] ? " del establecimiento «{$e['nombre']}»" : $donde;
        }
        // Una modificación muestra el valor anterior y el nuevo (sección 8.2).
        return ['resumen' => "Modificar la nota {$nota['id']}$donde",
            'detalle' => ["Antes: {$nota['texto']}", "Después: {$parametros['texto']}"], 'version' => $nota['version']];
    }

    public function ejecutar(array $parametros, string $usuarioId): array
    {
        if ($this->almacen->nota($usuarioId, $parametros['nota_id']) === null) {
            return Resultado::error('no_encontrado', 'No existe o no tenés acceso');
        }
        $nota = $this->almacen->modificarNota($usuarioId, $parametros['nota_id'], $parametros['texto']);
        return Resultado::ok(['mensaje' => 'Nota modificada.', 'nota' => $nota], 'notas');
    }
}
