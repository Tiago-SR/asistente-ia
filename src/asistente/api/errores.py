from fastapi import Request
from fastapi.responses import JSONResponse


class ErrorApi(Exception):
    def __init__(self, status: int, codigo: str, headers: dict[str, str] | None = None,
                 datos: dict | None = None) -> None:
        super().__init__(codigo)
        self.status, self.codigo, self.headers, self.datos = status, codigo, headers, datos


async def manejar_error_api(_: Request, e: ErrorApi) -> JSONResponse:
    return JSONResponse({"error": e.codigo, **(e.datos or {})}, status_code=e.status, headers=e.headers)
