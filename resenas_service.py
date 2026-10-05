import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, Field, ConfigDict


DB_PATH = Path(__file__).with_name("resenas.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


@asynccontextmanager
async def lifespan(app: FastAPI):

    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS resenas (
                resena_id INTEGER PRIMARY KEY AUTOINCREMENT,
                libro_id INTEGER NOT NULL,
                usuario_id INTEGER NOT NULL,
                calificacion INTEGER NOT NULL,
                comentario TEXT NOT NULL
            )
        """)

        conn.commit()

    yield


app = FastAPI(
    title="Servicio de Reseñas",
    description=(
        "Microservicio encargado de administrar "
        "comentarios y calificaciones de libros."
    ),
    version="1.0.0",
    lifespan=lifespan
)


class ResenaCreate(BaseModel):

    libro_id: int = Field(
        ...,
        gt=0,
        description="ID del libro reseñado",
        examples=[1]
    )

    usuario_id: int = Field(
        ...,
        gt=0,
        description="ID del usuario que realiza la reseña",
        examples=[1]
    )

    calificacion: int = Field(
        ...,
        ge=1,
        le=5,
        description="Calificación del libro entre 1 y 5 estrellas",
        examples=[5]
    )

    comentario: str = Field(
        ...,
        min_length=1,
        description="Comentario realizado por el usuario",
        examples=["Me pareció un excelente libro."]
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "libro_id": 1,
                "usuario_id": 1,
                "calificacion": 5,
                "comentario": "Me pareció un excelente libro."
            }
        }
    )


@app.get(
    "/",
    tags=["General"],
    summary="Verificar servicio"
)
def root():
    return {
        "servicio": "Reseñas",
        "version": "v1",
        "estado": "activo"
    }


@app.post(
    "/api/v1/resenas",
    status_code=status.HTTP_201_CREATED,
    tags=["Reseñas"],
    summary="Crear reseña",
    description=(
        "Registra una nueva reseña asociada "
        "a un libro y a un usuario."
    )
)
def crear_resena(resena: ResenaCreate):

    with get_db() as conn:

        cursor = conn.execute(
            """
            INSERT INTO resenas (
                libro_id,
                usuario_id,
                calificacion,
                comentario
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                resena.libro_id,
                resena.usuario_id,
                resena.calificacion,
                resena.comentario
            )
        )

        conn.commit()

        resena_id = cursor.lastrowid

    return {
        "message": "Reseña registrada correctamente",
        "resena_id": resena_id,
        "libro_id": resena.libro_id,
        "usuario_id": resena.usuario_id,
        "calificacion": resena.calificacion,
        "comentario": resena.comentario
    }


@app.get(
    "/api/v1/resenas/libro/{libro_id}",
    tags=["Reseñas"],
    summary="Consultar reseñas de un libro",
    description=(
        "Retorna las reseñas asociadas a un libro "
        "y calcula el promedio general de calificaciones."
    )
)
def obtener_resenas_libro(libro_id: int):

    with get_db() as conn:

        filas = conn.execute(
            """
            SELECT
                resena_id,
                libro_id,
                usuario_id,
                calificacion,
                comentario
            FROM resenas
            WHERE libro_id = ?
            """,
            (libro_id,)
        ).fetchall()

    if not filas:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No existen reseñas para este libro"
        )

    resenas = [dict(fila) for fila in filas]

    promedio = sum(
        resena["calificacion"]
        for resena in resenas
    ) / len(resenas)

    return {
        "libro_id": libro_id,
        "promedio": round(promedio, 2),
        "total_resenas": len(resenas),
        "resenas": resenas
    }