# multas_service.py
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field

USUARIOS_URL = "http://localhost:8002/usuarios"
DB_PATH = Path(__file__).with_name("multas.db")


class MultaCreate(BaseModel):
    usuario_id: int = Field(gt=0)
    monto: float = Field(gt=0)
    motivo: str = Field(min_length=1, max_length=255)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@asynccontextmanager
async def lifespan(app: FastAPI):
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS multas (
                multa_id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                monto REAL NOT NULL,
                motivo TEXT NOT NULL
            )
        """)
        # Impide dos préstamos activos del mismo libro.
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS un_prestamo_activo_por_libro
            ON prestamos(libro_id)
            WHERE activo = 1
        """)
    yield


app = FastAPI(title="Servicio de Préstamos", lifespan=lifespan)


async def verificar_recurso(client: httpx.AsyncClient, url: str, nombre: str):
    try:
        respuesta = await client.get(url)
    except httpx.RequestError:
        raise HTTPException(
            status_code=503,
            detail=f"No se pudo conectar con el servicio de {nombre}"
        )

    if respuesta.status_code == 404:
        raise HTTPException(
            status_code=404, detail=f"{nombre.capitalize()} no encontrado")

    if respuesta.status_code != 200:
        raise HTTPException(
            status_code=503,
            detail=f"El servicio de {nombre} respondió con error"
        )


@app.post("/prestamos", status_code=status.HTTP_201_CREATED)
async def crear_prestamo(datos: PrestamoCreate):
    # Estas rutas requieren GET /usuarios/{id} y GET /libros/{id}
    # en sus respectivos servicios.
    async with httpx.AsyncClient(timeout=5.0) as client:
        await verificar_recurso(
            client, f"{USUARIOS_URL}/{datos.usuario_id}", "usuario"
        )
        await verificar_recurso(
            client, f"{LIBROS_URL}/{datos.libro_id}", "libro"
        )

    try:
        with get_db() as conn:
            cursor = conn.execute(
                """
                INSERT INTO prestamos (usuario_id, libro_id, activo)
                VALUES (?, ?, 1)
                """,
                (datos.usuario_id, datos.libro_id)
            )
            prestamo_id = cursor.lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail="Este libro ya tiene un préstamo activo"
        )

    return {
        "prestamo_id": prestamo_id,
        "usuario_id": datos.usuario_id,
        "libro_id": datos.libro_id,
        "activo": True
    }


@app.patch("/prestamos/{prestamo_id}/devolver")
def devolver_libro(prestamo_id: int):
    with get_db() as conn:
        prestamo = conn.execute(
            "SELECT * FROM prestamos WHERE prestamo_id = ?",
            (prestamo_id,)
        ).fetchone()

        if prestamo is None:
            raise HTTPException(
                status_code=404, detail="Préstamo no encontrado")

        if not prestamo["activo"]:
            raise HTTPException(
                status_code=409, detail="El libro ya fue devuelto")

        conn.execute(
            "UPDATE prestamos SET activo = 0 WHERE prestamo_id = ?",
            (prestamo_id,)
        )

    return {
        "prestamo_id": prestamo_id,
        "usuario_id": prestamo["usuario_id"],
        "libro_id": prestamo["libro_id"],
        "activo": False
    }
