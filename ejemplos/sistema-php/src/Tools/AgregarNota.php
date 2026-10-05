<?php
declare(strict_types=1);

namespace Ejemplo\Tools;

use Ejemplo\Config;
use Ejemplo\Datos\Almacen;
use Ejemplo\Datos\Repositorio;

final class AgregarNota implements Accion
{
    public function __construct(private readonly Repositorio $repo, private readonly Almacen $almacen)
    {
    }

    public function nombre(): string
    {
        return 'agregar_nota';
    }

    public function definicion(): array
    {
        return [
            'nombre' => $this->nombre(),
            'descripcion' => 'Agrega una nota de texto a un establecimiento del usuario. El usuario debe confirmarla '
                . 'en pantalla antes de que se guarde. Resolver antes el id con listar_establecimientos.',
            'parametros' => [
                'type' => 'object',
                'properties' => [
                    'establecimiento_id' => ['type' => 'string', 'description' => 'id del establecimiento'],
                    'texto' => ['type' => 'string', 'description' => 'texto de la nota, solo lo que dijo el usuario', 'minLength' => 1, 'maxLength' => 500],
                ],
                'required' => ['establecimiento_id', 'texto'],
                'additionalProperties' => false,
            ],
            'efecto' => 'escritura',
            'confirmacion' => ['ttl_s' => Config::TTL_PROPUESTA_S],
            'timeout_s' => 15,
        ];
    }

    public function preparar(array $parametros, string $usuarioId): array
    {
        $est = $this->establecimiento($parametros['establecimiento_id'], $usuarioId);
        if ($est === null) {
            return Resultado::error('no_encontrado', 'No existe o no tenés acceso');
        }
        return ['resumen' => "Agregar una nota al establecimiento «{$est['nombre']}»",
            'detalle' => ["Texto: {$parametros['texto']}"], 'version' => null];
    }

    public function ejecutar(array $parametros, string $usuarioId): array
    {
        if ($this->establecimiento($parametros['establecimiento_id'], $usuarioId) === null) {
            return Resultado::error('no_encontrado', 'No existe o no tenés acceso');
        }
        $nota = $this->almacen->agregarNota($usuarioId, $parametros['establecimiento_id'], $parametros['texto']);
        return Resultado::ok(['mensaje' => 'Nota agregada.', 'nota' => $nota], 'notas');
    }

    private function establecimiento(string $id, string $usuarioId): ?array
    {
        foreach ($this->repo->establecimientosDe($usuarioId) as $e) {
            if ($e['id'] === $id) {
                return $e;
            }
        }
        return null;
    }
}
