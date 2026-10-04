<?php
declare(strict_types=1);

namespace Ejemplo\Tools;

/** Una tool del contrato. Ver contrato/GUIA_TOOLS.md. */
interface Herramienta
{
    public function nombre(): string;

    /** Entrada del manifiesto: nombre, descripcion, parametros (JSON Schema), efecto, timeout_s. */
    public function definicion(): array;

    /**
     * @param array $parametros ya validados contra el schema, pero siguen siendo input no confiable
     * @param string $usuarioId claim `sub`: el ÚNICO origen de la identidad
     * @return array resultado de negocio (ver Resultado)
     */
    public function ejecutar(array $parametros, string $usuarioId): array;
}
