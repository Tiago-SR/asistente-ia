<?php
declare(strict_types=1);

namespace Ejemplo\Tools;

use Opis\JsonSchema\Validator;

/** Catálogo de tools: arma el manifiesto y valida los parámetros contra el schema declarado. */
final class Registro
{
    /** @var array<string, Herramienta> */
    private array $tools = [];

    public function __construct(private readonly string $nombreSistema, private readonly string $version, Herramienta ...$tools)
    {
        foreach ($tools as $t) {
            $this->tools[$t->nombre()] = $t;
        }
    }

    public function manifiesto(): array
    {
        return [
            'contrato' => '1',
            'sistema' => ['nombre' => $this->nombreSistema, 'version' => $this->version],
            'tools' => array_values(array_map(fn(Herramienta $t) => $t->definicion(), $this->tools)),
        ];
    }

    public function buscar(string $nombre): ?Herramienta
    {
        return $this->tools[$nombre] ?? null;
    }

    /** Escritura con propuesta y confirmación (sección 8); las demás escrituras no se ejecutan nunca. */
    public function esAccion(Herramienta $t): bool
    {
        return $t instanceof Accion;
    }

    public function esLectura(Herramienta $t): bool
    {
        return ($t->definicion()['efecto'] ?? null) === 'lectura';
    }

    /** @return string|null mensaje de error, o null si los parámetros cumplen el schema */
    public function validar(Herramienta $t, object $parametros): ?string
    {
        $schema = json_decode(json_encode($t->definicion()['parametros'], JSON_THROW_ON_ERROR), false);
        $resultado = (new Validator())->validate($parametros, $schema);
        if ($resultado->isValid()) {
            return null;
        }
        return mb_substr($resultado->error()?->message() ?? 'parámetros inválidos', 0, 200);
    }
}
