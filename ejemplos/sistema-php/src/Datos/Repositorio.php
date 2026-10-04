<?php
declare(strict_types=1);

namespace Ejemplo\Datos;

/**
 * Datos ficticios en memoria, equivalentes a los del mock Python.
 * Un sistema real consulta su base de datos aplicando sus propios permisos.
 *
 * `id` del usuario = lo que va en el claim `sub`: estable, único por persona y nunca reutilizable.
 * No es el login ni el email (pueden cambiar o reasignarse).
 */
final class Repositorio
{
    private const USUARIOS = [
        'ana' => ['id' => 'u-1001', 'nombre' => 'Ana'],
        'beto' => ['id' => 'u-1002', 'nombre' => 'Beto'],
    ];

    /** @var array<string, list<array<string, mixed>>> por id de usuario */
    private const ESTABLECIMIENTOS = [
        'u-1001' => [
            ['id' => '1', 'nombre' => 'El Matorral', 'superficie_ha' => 540.5, 'cultivo' => 'soja'],
            ['id' => '2', 'nombre' => 'La Esperanza', 'superficie_ha' => 210.0, 'cultivo' => 'maíz'],
            ['id' => '4', 'nombre' => 'San Pedro', 'superficie_ha' => 120.0, 'cultivo' => 'soja'],
        ],
        'u-1002' => [
            ['id' => '3', 'nombre' => 'Los Ceibos', 'superficie_ha' => 88.2, 'cultivo' => 'trigo'],
        ],
    ];

    /** @return array{id: string, nombre: string}|null */
    public function usuarioPorLogin(string $login): ?array
    {
        return self::USUARIOS[$login] ?? null;
    }

    /** @return list<array<string, mixed>> solo lo que el usuario puede ver */
    public function establecimientosDe(string $usuarioId): array
    {
        return self::ESTABLECIMIENTOS[$usuarioId] ?? [];
    }
}
