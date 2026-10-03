# multas_service.py
import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field


USUARIOS_URL = os.getenv(
    "USUARIOS_URL",
    "http://localhost:8002/usuarios"
).rstrip("/")

DB_PATH = Path(__file__).with_name("multas.db")


class MultaCreate(BaseModel):
    usuario_id: int = Field(
        gt=0,
        description="ID del usuario que recibe la multa"
    )
    monto: float = Field(
        gt=0,
        allow_inf_nan=False,
        description="Importe de la multa, mayor que cero"
    )
    motivo: str = Field(
        min_length=1,
        max_length=255,
        description="Motivo por el que se asigna la multa"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "usuario_id": 1,
                    "monto": 50.0,
                    "motivo": "Devolución fuera de tiempo"
                }
            ]
        }
    }


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    try:
        with conn:
            yield conn
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS multas (
                multa_id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                monto REAL NOT NULL,
                motivo TEXT NOT NULL,
                pagada BOOLEAN NOT NULL DEFAULT 0
            )
        """)

        # Actualiza la tabla anterior sin eliminar sus registros.
        columnas = conn.execute("PRAGMA table_info(multas)").fetchall()

        if "pagada" not in [columna["name"] for columna in columnas]:
            conn.execute("""
                ALTER TABLE multas
                ADD COLUMN pagada BOOLEAN NOT NULL DEFAULT 0
            """)

    yield


app = FastAPI(
    title="Servicio de Multas y Sanciones",
    description="Administra multas, pagos y bloqueo por adeudos.",
    version="1.0.0",
    lifespan=lifespan
)


async def verificar_usuario(usuario_id: int):
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            respuesta = await client.get(
                f"{USUARIOS_URL}/{usuario_id}"
            )
    except httpx.RequestError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No se pudo conectar con el servicio de usuarios"
        )

    if respuesta.status_code == 404:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado"
        )

    if respuesta.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="El servicio de usuarios respondió con error"
        )


def convertir_multa(multa):
    return {
        "multa_id": multa["multa_id"],
        "usuario_id": multa["usuario_id"],
        "monto": multa["monto"],
        "motivo": multa["motivo"],
        "pagada": bool(multa["pagada"])
    }


@app.post(
    "/multas",
    status_code=status.HTTP_201_CREATED,
    summary="Crear una multa",
    description=(
        "Verifica que el usuario exista y registra una multa "
        "con estado inicial pagada = False."
    ),
    tags=["Multas"]
)
async def crear_multa(datos: MultaCreate):
    motivo = datos.motivo.strip()

    if not motivo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El motivo no puede contener solamente espacios"
        )

    monto = round(datos.monto, 2)

    if monto <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El monto mínimo es 0.01"
        )

    await verificar_usuario(datos.usuario_id)

    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO multas (usuario_id, monto, motivo, pagada)
            VALUES (?, ?, ?, 0)
            """,
            (datos.usuario_id, monto, motivo)
        )

        multa = conn.execute(
            "SELECT * FROM multas WHERE multa_id = ?",
            (cursor.lastrowid,)
        ).fetchone()

    return convertir_multa(multa)


@app.get(
    "/multas/{multa_id}",
    summary="Consultar una multa",
    description="Obtiene los datos de una multa y su estado de pago.",
    tags=["Multas"]
)
def obtener_multa(multa_id: int):
    with get_db() as conn:
        multa = conn.execute(
            "SELECT * FROM multas WHERE multa_id = ?",
            (multa_id,)
        ).fetchone()

    if not multa:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Multa no encontrada"
        )

    return convertir_multa(multa)


@app.patch(
    "/multas/{multa_id}/pagar",
    summary="Pagar una multa",
    description=(
        "Cambia el estado de una multa pendiente a pagada = True. "
        "Rechaza el pago si la multa ya estaba pagada."
    ),
    tags=["Multas"]
)
def pagar_multa(multa_id: int):
    with get_db() as conn:
        cursor = conn.execute(
            """
            UPDATE multas
            SET pagada = 1
            WHERE multa_id = ? AND pagada = 0
            """,
            (multa_id,)
        )

        multa = conn.execute(
            "SELECT * FROM multas WHERE multa_id = ?",
            (multa_id,)
        ).fetchone()

        if not multa:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Multa no encontrada"
            )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Esta multa ya fue pagada"
            )

    return convertir_multa(multa)


@app.get(
    "/sanciones/usuario/{usuario_id}/estatus",
    summary="Consultar sanciones de un usuario",
    description=(
        "Devuelve el monto total adeudado y la bandera bloqueado. "
        "El usuario está bloqueado mientras tenga multas sin pagar."
    ),
    tags=["Sanciones"]
)
async def obtener_estatus(usuario_id: int):
    await verificar_usuario(usuario_id)

    with get_db() as conn:
        resultado = conn.execute(
            """
            SELECT
                COALESCE(SUM(monto), 0) AS total_adeudado,
                COUNT(*) AS multas_pendientes
            FROM multas
            WHERE usuario_id = ? AND pagada = 0
            """,
            (usuario_id,)
        ).fetchone()

    return {
        "usuario_id": usuario_id,
        "total_adeudado": round(resultado["total_adeudado"], 2),
        "bloqueado": resultado["multas_pendientes"] > 0
    }
