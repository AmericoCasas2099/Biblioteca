import sqlite3
from contextlib import asynccontextmanager, contextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, Field, field_validator


class LibroCreate(BaseModel):
    titulo: str = Field(
        min_length=1,
        description="Título del libro"
    )
    autor: str = Field(
        min_length=1,
        description="Nombre del autor"
    )

    @field_validator("titulo", "autor")
    @classmethod
    def validar_texto(cls, valor: str):
        valor = valor.strip()
        if not valor:
            raise ValueError("El campo no puede contener solamente espacios")
        return valor

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "titulo": "El principito",
                    "autor": "Antoine de Saint-Exupéry"
                }
            ]
        }
    }


class LibroUpdate(BaseModel):
    titulo: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Nuevo título; omitir para conservar el actual"
    )
    autor: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Nuevo autor; omitir para conservar el actual"
    )

    @field_validator("titulo", "autor")
    @classmethod
    def validar_texto(cls, valor: Optional[str]):
        if valor is None:
            raise ValueError("Omite el campo si no deseas modificarlo")

        valor = valor.strip()
        if not valor:
            raise ValueError("El campo no puede contener solamente espacios")
        return valor

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"titulo": "El principito (edición ilustrada)"}
            ]
        }
    }


class DisponibilidadUpdate(BaseModel):
    disponible: bool = Field(
        description="True si el libro está disponible; False si está prestado"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"disponible": False}
            ]
        }
    }


@contextmanager
def get_db():
    conn = sqlite3.connect("libros.db")
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
            CREATE TABLE IF NOT EXISTS libros (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                titulo TEXT NOT NULL,
                autor TEXT NOT NULL,
                disponible BOOLEAN NOT NULL DEFAULT 1
            )
        """)
    yield


app = FastAPI(
    title="Servicio de Libros",
    description="Gestiona el catálogo de libros y su disponibilidad.",
    version="1.0.0",
    lifespan=lifespan
)


def convertir_libro(row):
    return {
        "id": row["id"],
        "titulo": row["titulo"],
        "autor": row["autor"],
        "disponible": bool(row["disponible"])
    }


def buscar_libro(conn, libro_id: int):
    row = conn.execute(
        "SELECT * FROM libros WHERE id = ?",
        (libro_id,)
    ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Libro no encontrado"
        )

    return row


@app.post(
    "/libros",
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un libro",
    description="Crea un libro con disponibilidad inicial en True.",
    tags=["Libros"]
)
def crear_libro(libro: LibroCreate):
    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO libros (titulo, autor, disponible)
            VALUES (?, ?, 1)
            """,
            (libro.titulo, libro.autor)
        )

        row = buscar_libro(conn, cursor.lastrowid)

    return convertir_libro(row)


@app.get(
    "/libros",
    summary="Consultar el catálogo",
    description=(
        "Devuelve los libros ordenados por título. "
        "Si no hay registros, devuelve una lista vacía."
    ),
    tags=["Libros"]
)
def obtener_libros():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM libros ORDER BY titulo COLLATE NOCASE, id"
        ).fetchall()

    return [convertir_libro(row) for row in rows]


@app.get(
    "/libros/{libro_id}",
    summary="Consultar un libro",
    description="Devuelve los datos y la disponibilidad de un libro por su ID.",
    tags=["Libros"],
    responses={404: {"description": "Libro no encontrado"}}
)
def obtener_libro(libro_id: int):
    with get_db() as conn:
        row = buscar_libro(conn, libro_id)

    return convertir_libro(row)


@app.patch(
    "/libros/{libro_id}",
    summary="Editar un libro",
    description=(
        "Actualiza el título, el autor o ambos. "
        "Los campos omitidos conservan su valor actual."
    ),
    tags=["Libros"],
    responses={
        400: {"description": "No se enviaron campos para actualizar"},
        404: {"description": "Libro no encontrado"}
    }
)
def editar_libro(libro_id: int, payload: LibroUpdate):
    cambios = payload.model_dump(exclude_unset=True)

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = buscar_libro(conn, libro_id)

        if not cambios:
            raise HTTPException(
                status_code=400,
                detail="Debes enviar al menos el título o el autor"
            )

        nuevo_titulo = cambios.get("titulo", row["titulo"])
        nuevo_autor = cambios.get("autor", row["autor"])

        conn.execute(
            "UPDATE libros SET titulo = ?, autor = ? WHERE id = ?",
            (nuevo_titulo, nuevo_autor, libro_id)
        )

        actualizado = buscar_libro(conn, libro_id)

    return convertir_libro(actualizado)


@app.patch(
    "/libros/{libro_id}/disponibilidad",
    summary="Actualizar la disponibilidad",
    description=(
        "Establece disponible en False al prestar el libro "
        "y en True al devolverlo."
    ),
    tags=["Libros"],
    responses={404: {"description": "Libro no encontrado"}}
)
def actualizar_disponibilidad(
    libro_id: int,
    payload: DisponibilidadUpdate
):
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        buscar_libro(conn, libro_id)

        conn.execute(
            "UPDATE libros SET disponible = ? WHERE id = ?",
            (int(payload.disponible), libro_id)
        )

        actualizado = buscar_libro(conn, libro_id)

    return convertir_libro(actualizado)


@app.delete(
    "/libros/{libro_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un libro",
    description=(
        "Elimina un libro únicamente si está disponible. "
        "Si está prestado, devuelve un error 400."
    ),
    tags=["Libros"],
    responses={
        400: {"description": "El libro está prestado"},
        404: {"description": "Libro no encontrado"}
    }
)
def eliminar_libro(libro_id: int):
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = buscar_libro(conn, libro_id)

        if not row["disponible"]:
            raise HTTPException(
                status_code=400,
                detail="No se puede eliminar un libro que está prestado"
            )

        conn.execute(
            "DELETE FROM libros WHERE id = ?",
            (libro_id,)
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
