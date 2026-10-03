from fastapi import Request
from fastapi.responses import JSONResponse


class ErrorApi(Exception):
    def __init__(self, status: int, codigo: str, headers: dict[str, str] | None = None) -> None:
        super().__init__(codigo)
        self.status, self.codigo, self.headers = status, codigo, headers


async def manejar_error_api(_: Request, e: ErrorApi) -> JSONResponse:
    return JSONResponse({"error": e.codigo}, status_code=e.status, headers=e.headers)
