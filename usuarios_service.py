# usuarios_service.py
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator


class UsuarioCreate(BaseModel):
    nombre: str = Field(
        min_length=1,
        description="Nombre del usuario"
    )
    email: EmailStr = Field(
        description="Correo electrónico válido y único"
    )

    @field_validator("nombre")
    @classmethod
    def validar_nombre(cls, valor: str):
        valor = valor.strip()
        if not valor:
            raise ValueError("El nombre no puede contener solo espacios")
        return valor

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "nombre": "Ana García",
                    "email": "ana@example.com"
                }
            ]
        }
    }


class UsuarioUpdate(BaseModel):
    nombre: Optional[str] = Field(
        default=None,
        min_length=1,
        description="Nuevo nombre; omitir para conservar el actual"
    )
    email: Optional[EmailStr] = Field(
        default=None,
        description="Nuevo correo válido y único"
    )

    @field_validator("nombre", "email")
    @classmethod
    def validar_campos(cls, valor):
        if valor is None:
            raise ValueError("Omite el campo si no deseas modificarlo")

        valor = valor.strip()
        if not valor:
            raise ValueError("El campo no puede contener solo espacios")

        return valor

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {"email": "ana.garcia@example.com"}
            ]
        }
    }


@contextmanager
def get_db():
    conn = sqlite3.connect("usuarios.db")
    conn.row_factory = sqlite3.Row

    try:
        with conn:
            yield conn
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                email TEXT NOT NULL
            )
        """)

        columnas = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(usuarios)")
        }

        if (
            "apellido" in columnas
            or "activo" in columnas
            or "email" not in columnas
        ):
            # Conserva el contador para no reutilizar IDs eliminados.
            secuencia = conn.execute(
                "SELECT seq FROM sqlite_sequence WHERE name = 'usuarios'"
            ).fetchone()

            ultimo_id = secuencia["seq"] if secuencia else 0

            # Email admite NULL durante la migración para conservar
            # los usuarios antiguos que todavía no tienen correo.
            conn.execute("""
                CREATE TABLE usuarios_migracion (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre TEXT NOT NULL,
                    email TEXT
                )
            """)

            if "email" in columnas:
                conn.execute("""
                    INSERT INTO usuarios_migracion (id, nombre, email)
                    SELECT id, nombre, email FROM usuarios
                """)
            else:
                conn.execute("""
                    INSERT INTO usuarios_migracion (id, nombre, email)
                    SELECT id, nombre, NULL FROM usuarios
                """)

            conn.execute("DROP TABLE usuarios")
            conn.execute(
                "ALTER TABLE usuarios_migracion RENAME TO usuarios"
            )

            conn.execute(
                """
                UPDATE sqlite_sequence
                SET seq = MAX(seq, ?)
                WHERE name = 'usuarios'
                """,
                (ultimo_id,)
            )

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS email_unico_usuarios
            ON usuarios(email COLLATE NOCASE)
        """)

    yield


app = FastAPI(
    title="Servicio de Usuarios",
    description="Administra lectores y valida sus correos electrónicos.",
    version="1.0.0",
    lifespan=lifespan
)


def buscar_usuario(conn, usuario_id: int):
    row = conn.execute(
        "SELECT id, nombre, email FROM usuarios WHERE id = ?",
        (usuario_id,)
    ).fetchone()

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Usuario no encontrado"
        )

    return row


def verificar_email_unico(conn, email: str, excluir_id=None):
    row = conn.execute(
        "SELECT id FROM usuarios WHERE email = ? COLLATE NOCASE",
        (email,)
    ).fetchone()

    if row is not None and row["id"] != excluir_id:
        raise HTTPException(
            status_code=400,
            detail="El correo electrónico ya está registrado"
        )


@app.get(
    "/",
    tags=["General"],
    summary="Verificar servicio"
)
def verificar_servicio():
    return {"message": "Servicio en funcionamiento"}


@app.post(
    "/api/v1/usuarios",
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un usuario",
    description="Crea un usuario con nombre y correo válido y único.",
    tags=["Usuarios"],
    responses={400: {"description": "Correo ya registrado"}}
)
def crear_usuario(usuario: UsuarioCreate):
    email = str(usuario.email)

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        verificar_email_unico(conn, email)

        cursor = conn.execute(
            "INSERT INTO usuarios (nombre, email) VALUES (?, ?)",
            (usuario.nombre, email)
        )

        row = buscar_usuario(conn, cursor.lastrowid)

    return dict(row)


@app.get(
    "/api/v1/usuarios",
    summary="Listar usuarios",
    description=(
        "Devuelve todos los usuarios ordenados por nombre. "
        "Si no hay registros, devuelve una lista vacía."
    ),
    tags=["Usuarios"]
)
def obtener_usuarios():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, nombre, email
            FROM usuarios
            ORDER BY nombre COLLATE NOCASE, id
        """).fetchall()

    return [dict(row) for row in rows]


@app.get(
    "/api/v1/usuarios/{usuario_id}",
    summary="Consultar un usuario",
    description="Obtiene el ID, nombre y correo de un usuario.",
    tags=["Usuarios"],
    responses={404: {"description": "Usuario no encontrado"}}
)
def obtener_usuario(usuario_id: int):
    with get_db() as conn:
        row = buscar_usuario(conn, usuario_id)

    return dict(row)


@app.patch(
    "/api/v1/usuarios/{usuario_id}",
    summary="Editar un usuario",
    description=(
        "Modifica nombre, correo o ambos. Conserva los campos "
        "omitidos y verifica que el correo sea único."
    ),
    tags=["Usuarios"],
    responses={
        400: {"description": "Correo duplicado o petición vacía"},
        404: {"description": "Usuario no encontrado"}
    }
)
def editar_usuario(usuario_id: int, payload: UsuarioUpdate):
    cambios = payload.model_dump(exclude_unset=True)

    with get_db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        actual = buscar_usuario(conn, usuario_id)

        if not cambios:
            raise HTTPException(
                status_code=400,
                detail="Debes enviar nombre o email para actualizar"
            )

        nombre = cambios.get("nombre", actual["nombre"])
        email = actual["email"]

        if "email" in cambios:
            email = str(cambios["email"])
            verificar_email_unico(conn, email, excluir_id=usuario_id)

        conn.execute(
            "UPDATE usuarios SET nombre = ?, email = ? WHERE id = ?",
            (nombre, email, usuario_id)
        )

        actualizado = buscar_usuario(conn, usuario_id)

    return dict(actualizado)


@app.delete(
    "/api/v1/usuarios/{usuario_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un usuario",
    description="Elimina definitivamente el perfil y devuelve una respuesta vacía.",
    tags=["Usuarios"],
    responses={404: {"description": "Usuario no encontrado"}}
)
def eliminar_usuario(usuario_id: int):
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM usuarios WHERE id = ?",
            (usuario_id,)
        )

        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Usuario no encontrado"
            )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
