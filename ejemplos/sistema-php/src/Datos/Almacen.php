<?php
declare(strict_types=1);

namespace Ejemplo\Datos;

/**
 * Estado que las acciones con confirmación necesitan entre peticiones: notas, propuestas vigentes,
 * tokens de escritura gastados y resultados idempotentes. SQLite para que el ejemplo funcione con el
 * servidor embebido (que no comparte memoria entre peticiones); un sistema real usa su base de datos.
 */
final class Almacen
{
    private \PDO $db;

    public function __construct(string $ruta = ':memory:')
    {
        $this->db = new \PDO('sqlite:' . $ruta, null, null, [
            \PDO::ATTR_ERRMODE => \PDO::ERRMODE_EXCEPTION,
            \PDO::ATTR_DEFAULT_FETCH_MODE => \PDO::FETCH_ASSOC,
        ]);
        $this->db->exec('PRAGMA busy_timeout = 3000');
        $this->db->exec(
            'CREATE TABLE IF NOT EXISTS notas (seq INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id TEXT NOT NULL,
                establecimiento_id TEXT NOT NULL, texto TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1);
             CREATE TABLE IF NOT EXISTS propuestas (huella TEXT PRIMARY KEY, sub TEXT NOT NULL, tool TEXT NOT NULL,
                parametros TEXT NOT NULL, version INTEGER, exp INTEGER NOT NULL);
             CREATE TABLE IF NOT EXISTS jti_usados (jti TEXT PRIMARY KEY);
             CREATE TABLE IF NOT EXISTS idempotencia (clave TEXT NOT NULL, sub TEXT NOT NULL, tool TEXT NOT NULL,
                huella TEXT NOT NULL, respuesta TEXT NOT NULL, PRIMARY KEY (clave, sub));'
        );
        if ($this->db->query('SELECT COUNT(*) FROM notas')->fetchColumn() == 0) {
            $this->agregarNota('u-1001', '1', 'Revisar el alambrado del potrero norte');
        }
    }

    // ── notas ──
    /** @return list<array{id: string, establecimiento_id: string, texto: string, version: int}> */
    public function notasDe(string $usuarioId, ?string $establecimientoId = null): array
    {
        $q = $this->db->prepare('SELECT * FROM notas WHERE usuario_id = ? ORDER BY seq');
        $q->execute([$usuarioId]);
        $notas = array_map(self::aNota(...), $q->fetchAll());
        return array_values(array_filter(
            $notas,
            fn(array $n) => $establecimientoId === null || $n['establecimiento_id'] === $establecimientoId,
        ));
    }

    public function nota(string $usuarioId, string $id): ?array
    {
        if (!preg_match('/^n(\d{1,12})$/', $id, $m)) {
            return null;
        }
        $q = $this->db->prepare('SELECT * FROM notas WHERE usuario_id = ? AND seq = ?');
        $q->execute([$usuarioId, (int) $m[1]]);
        $fila = $q->fetch();
        return $fila ? self::aNota($fila) : null;
    }

    public function agregarNota(string $usuarioId, string $establecimientoId, string $texto): array
    {
        $this->db->prepare('INSERT INTO notas (usuario_id, establecimiento_id, texto) VALUES (?, ?, ?)')
            ->execute([$usuarioId, $establecimientoId, $texto]);
        return $this->nota($usuarioId, 'n' . $this->db->lastInsertId());
    }

    public function modificarNota(string $usuarioId, string $id, string $texto): array
    {
        $this->db->prepare('UPDATE notas SET texto = ?, version = version + 1 WHERE usuario_id = ? AND seq = ?')
            ->execute([$texto, $usuarioId, (int) substr($id, 1)]);
        return $this->nota($usuarioId, $id);
    }

    private static function aNota(array $f): array
    {
        return ['id' => 'n' . $f['seq'], 'establecimiento_id' => $f['establecimiento_id'],
            'texto' => $f['texto'], 'version' => (int) $f['version']];
    }

    // ── propuestas ──
    public function guardarPropuesta(string $huella, string $sub, string $tool, array $parametros, ?int $version, int $exp): void
    {
        $this->db->prepare('DELETE FROM propuestas WHERE exp < ?')->execute([time()]);
        $this->db->prepare('INSERT OR REPLACE INTO propuestas (huella, sub, tool, parametros, version, exp) VALUES (?, ?, ?, ?, ?, ?)')
            ->execute([$huella, $sub, $tool, self::canonico($parametros), $version, $exp]);
    }

    /** @return array{sub: string, tool: string, parametros: array, version: ?int, exp: int}|null solo si sigue vigente */
    public function propuestaVigente(string $huella): ?array
    {
        $q = $this->db->prepare('SELECT * FROM propuestas WHERE huella = ? AND exp >= ?');
        $q->execute([$huella, time()]);
        $f = $q->fetch();
        if (!$f) {
            return null;
        }
        return ['sub' => $f['sub'], 'tool' => $f['tool'], 'parametros' => json_decode($f['parametros'], true),
            'version' => $f['version'] === null ? null : (int) $f['version'], 'exp' => (int) $f['exp']];
    }

    // ── un solo uso ──
    /** true si el `jti` no se había usado (la inserción es atómica: dos peticiones no pasan las dos). */
    public function gastarJti(string $jti): bool
    {
        $q = $this->db->prepare('INSERT OR IGNORE INTO jti_usados (jti) VALUES (?)');
        $q->execute([$jti]);
        return $q->rowCount() === 1;
    }

    // ── idempotencia ──
    /** @return array{tool: string, huella: string, respuesta: array}|null */
    public function resultadoPrevio(string $clave, string $sub): ?array
    {
        $q = $this->db->prepare('SELECT tool, huella, respuesta FROM idempotencia WHERE clave = ? AND sub = ?');
        $q->execute([$clave, $sub]);
        $f = $q->fetch();
        return $f ? ['tool' => $f['tool'], 'huella' => $f['huella'], 'respuesta' => json_decode($f['respuesta'], true)] : null;
    }

    public function guardarResultado(string $clave, string $sub, string $tool, string $huella, array $respuesta): void
    {
        $this->db->prepare('INSERT OR IGNORE INTO idempotencia (clave, sub, tool, huella, respuesta) VALUES (?, ?, ?, ?, ?)')
            ->execute([$clave, $sub, $tool, $huella, json_encode($respuesta, JSON_UNESCAPED_UNICODE)]);
    }

    /** Forma canónica (claves ordenadas): base de la huella y de la comparación de parámetros. */
    public static function canonico(mixed $valor): string
    {
        $ordenar = function (mixed $v) use (&$ordenar) {
            if (is_array($v)) {
                array_is_list($v) || ksort($v);
                return array_map($ordenar, $v);
            }
            return $v;
        };
        return json_encode($ordenar($valor), JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_THROW_ON_ERROR);
    }
}
