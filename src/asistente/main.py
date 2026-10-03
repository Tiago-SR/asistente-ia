from fastapi import FastAPI

app = FastAPI(title="Asistente", version="0.1.0")


@app.get("/salud")
async def salud() -> dict[str, bool]:
    return {"ok": True}
