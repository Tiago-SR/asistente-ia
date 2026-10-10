<?php
declare(strict_types=1);

// Router mínimo para servidor embebido (`php -S ... public/index.php`). En CI4 esto es app/Config/Routes.php.
require __DIR__ . '/../vendor/autoload.php';

use Ejemplo\Config;
use Ejemplo\Datos\Repositorio;
use Ejemplo\Fabrica;
use Ejemplo\Respuesta;

$cfg = Config::desdeEntorno();
$metodo = $_SERVER['REQUEST_METHOD'];
$ruta = rtrim(parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH) ?: '/', '/') ?: '/';
$auth = $_SERVER['HTTP_AUTHORIZATION'] ?? null;

function emitir(Respuesta $r): never
{
    http_response_code($r->estado);
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    echo json_encode($r->cuerpo, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    exit;
}

/** Login de la sesión del sistema. Demo: cookie simulada; un sistema real usa su propia sesión. */
function usuarioDeSesion(): ?string
{
    return isset($_COOKIE['usuario']) && is_string($_COOKIE['usuario']) ? $_COOKIE['usuario'] : null;
}

$ctl = Fabrica::controlador($cfg);

if ($ruta === '/asistente/salud' && $metodo === 'GET') {
    emitir($ctl->salud());
}
if ($ruta === '/asistente/token' && $metodo === 'GET') {
    $prueba = isset($_GET['usuario']) && is_string($_GET['usuario']) ? $_GET['usuario'] : null;
    $conf = isset($_GET['confirmacion']) && is_string($_GET['confirmacion']) ? $_GET['confirmacion'] : null;
    $huella = isset($_GET['huella']) && is_string($_GET['huella']) ? $_GET['huella'] : null;
    emitir($ctl->token(usuarioDeSesion(), $prueba, $conf, $huella));
}
if ($ruta === '/asistente/tools' && $metodo === 'GET') {
    emitir($ctl->manifiesto($auth));
}
if ($metodo === 'POST' && preg_match('#^/asistente/tools/([a-z][a-z0-9_]{0,63})(/propuesta)?$#', $ruta, $m)) {
    $cuerpo = file_get_contents('php://input') ?: '';
    emitir(isset($m[2])
        ? $ctl->propuesta($m[1], $auth, $cuerpo)
        : $ctl->ejecutar($m[1], $auth, $cuerpo, $_SERVER['HTTP_IDEMPOTENCY_KEY'] ?? null));
}
if (str_starts_with($ruta, '/asistente/')) {
    emitir(Respuesta::http(404, 'no encontrado'));
}

// ── Páginas de demostración (HTML con el widget) ──
$usuario = isset($_GET['usuario']) && is_string($_GET['usuario']) ? $_GET['usuario'] : (usuarioDeSesion() ?? 'ana');
if ($cfg->local && isset($_GET['usuario'])) {
    setcookie('usuario', $usuario, ['path' => '/', 'httponly' => true, 'samesite' => 'Lax']);
}
if ($ruta === '/') {
    $titulo = $cfg->nombre;
    $cuerpo = "Sesión simulada como «{$usuario}».";
} elseif (preg_match('#^/establecimientos/([0-9]+)$#', $ruta, $m)) {
    $repo = new Repositorio();
    $u = $repo->usuarioPorLogin($usuario);
    $est = null;
    foreach ($u ? $repo->establecimientosDe($u['id']) : [] as $e) {
        $est = $e['id'] === $m[1] ? $e : $est;
    }
    if ($est === null) {
        http_response_code(404);
        exit('no encontrado');
    }
    $titulo = $est['nombre'];
    $cuerpo = "{$est['superficie_ha']} ha de {$est['cultivo']}.";
} else {
    http_response_code(404);
    exit('no encontrado');
}
$h = fn(string $s) => htmlspecialchars($s, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
header('Content-Type: text/html; charset=utf-8');
?>
<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title><?= $h($titulo) ?></title></head>
<body style="margin:0;height:100vh;display:flex;flex-direction:column;font-family:system-ui">
<nav style="padding:8px 16px;font-size:13px;border-bottom:1px solid #d9ded9">
<strong><?= $h($titulo) ?></strong> · <?= $h($cuerpo) ?><?php if ($cfg->local): ?> · usuario de prueba: <a href="/?usuario=ana">ana</a> · <a href="/?usuario=beto">beto</a><?php endif; ?>
</nav>
<script src="<?= $h($cfg->asistenteUrl) ?>/widget.js" defer></script>
<asistente-chat style="flex:1;min-height:0"<?= $cfg->local && ($_GET['orbe'] ?? '') === 'no' ? ' orbe-volumen="no"' : '' ?> servidor="<?= $h($cfg->asistenteUrl) ?>" token-url="/asistente/token<?= $cfg->local ? '?usuario=' . $h(rawurlencode($usuario)) : '' ?>"></asistente-chat>
</body></html>
