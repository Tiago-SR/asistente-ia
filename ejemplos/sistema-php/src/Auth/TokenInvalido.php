<?php
declare(strict_types=1);

namespace Ejemplo\Auth;

/** Token ilegible, mal firmado, vencido o de otro emisor/audiencia → HTTP 401. */
final class TokenInvalido extends \RuntimeException
{
}
