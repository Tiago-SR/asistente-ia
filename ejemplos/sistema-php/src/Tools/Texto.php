<?php
declare(strict_types=1);

namespace Ejemplo\Tools;

final class Texto
{
    /** Minúsculas y sin tildes, para filtros "contiene". */
    public static function normalizar(string $s): string
    {
        return strtr(mb_strtolower($s), ['á' => 'a', 'é' => 'e', 'í' => 'i', 'ó' => 'o', 'ú' => 'u', 'ü' => 'u', 'ñ' => 'n']);
    }
}
