import sqlite3
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel
from typing import Optional


class UsuarioUpdate(BaseModel):
    nombre: Optional[str] = None
    apellido: Optional[str] = None


def get_db():
    conn = sqlite3.connect("usuarios.db")
    conn.row_factory = sqlite3.Row
    return conn


@asynccontextmanager
async def lifespan(app: FastAPI):
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                apellido TEXT NOT NULL,
                activo BOOLEAN NOT NULL DEFAULT 1
            )
        """)
    yield

app = FastAPI(title="Servicio de Usuarios", lifespan=lifespan)


class UsuarioCreate(BaseModel):
    nombre: str
    apellido: str


class ActivoUpdate(BaseModel):
    activo: bool


@app.post("/usuarios", status_code=status.HTTP_201_CREATED)
def crear_usuario(usuario: UsuarioCreate):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO usuarios (nombre, apellido, activo) VALUES (?, ?, 1)",
            (usuario.nombre, usuario.apellido)
        )
        usuario_id = cursor.lastrowid
        return {"id": usuario_id, "nombre": usuario.nombre, "apellido": usuario.apellido, "activo": True}


@app.get("/usuarios", status_code=status.HTTP_200_OK)
def obtener_usuarios():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM usuarios ORDER BY nombre").fetchall()
        if not rows:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                detail="No existen usuarios registrados")
        return [dict(row) for row in rows]


@app.get("/usuarios/{usuario_id}")
def obtener_usuario(usuario_id: int):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if not row:
            raise HTTPException(
                status_code=404, detail="Usuario no encontrado")
        return dict(row)


@app.patch("/usuarios/{usuario_id}/activo")
def actualizar_activo(usuario_id: int, payload: ActivoUpdate):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if not row:
            raise HTTPException(
                status_code=404, detail="Usuario no encontrado")

        conn.execute(
            "UPDATE usuarios SET activo = ? WHERE id = ?",
            (1 if payload.activo else 0, usuario_id)
        )
        return {"id": usuario_id, "activo": payload.activo}


@app.patch("/usuarios/{usuario_id}")
def editar_usuario(usuario_id: int, payload: UsuarioUpdate):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
        if not row:
            raise HTTPException(
                status_code=404, detail="Usuario no encontrado")

        usuario_actual = dict(row)

        # Mantiene el valor actual si el campo no se envió en la petición
        nuevo_nombre = payload.nombre if payload.nombre is not None else usuario_actual[
            "nombre"]
        nuevo_apellido = payload.apellido if payload.apellido is not None else usuario_actual[
            "apellido"]

        conn.execute(
            "UPDATE usuarios SET nombre = ?, apellido = ? WHERE id = ?",
            (nuevo_nombre, nuevo_apellido, usuario_id)
        )

        return {**usuario_actual, "nombre": nuevo_nombre, "apellido": nuevo_apellido}


@app.delete("/usuarios/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_usuario(usuario_id: int):
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE usuarios SET activo = 0 WHERE id = ?",
            (usuario_id,)
        )
        if cursor.rowcount == 0:
            raise HTTPException(
                status_code=404,
                detail="Usuario no encontrado"
            )

    return None
