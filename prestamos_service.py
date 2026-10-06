# prestamos_service.py
import asyncio
import logging
import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, HTTPException, status
from pydantic import BaseModel, Field


LIBROS_URL = os.getenv(
    "LIBROS_URL", "http://localhost:8001/libros"
).rstrip("/")

USUARIOS_URL = os.getenv(
    "USUARIOS_URL", "http://localhost:8002/usuarios"
).rstrip("/")

SANCIONES_URL = os.getenv(
    "SANCIONES_URL", "http://localhost:8005/sanciones"
).rstrip("/")

NOTIFICACIONES_URL = os.getenv(
    "NOTIFICACIONES_URL",
    "http://localhost:8004/api/v1/notificaciones/enviar"
)

DB_PATH = Path(__file__).with_name("prestamos.db")
logger = logging.getLogger("uvicorn.error")


class PrestamoCreate(BaseModel):
    usuario_id: int = Field(
        gt=0,
        description="ID del usuario que solicita el préstamo"
    )
    libro_id: int = Field(
        gt=0,
        description="ID del libro que se desea prestar"
    )

    model_config = {
        "extra": "forbid",
        "json_schema_extra": {
            "examples": [
                {
                    "usuario_id": 1,
                    "libro_id": 2
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
            CREATE TABLE IF NOT EXISTS prestamos (
                prestamo_id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                libro_id INTEGER NOT NULL,
                activo INTEGER NOT NULL DEFAULT 1
            )
        """)

        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS un_prestamo_activo_por_libro
            ON prestamos(libro_id)
            WHERE activo = 1
        """)

    # Evita que dos operaciones de este proceso se intercalen
    # al comprobar límites y modificar préstamos.
    app.state.operaciones = asyncio.Lock()

    yield


app = FastAPI(
    title="Servicio de Préstamos",
    description=(
        "Orquesta préstamos y devoluciones mediante los servicios "
        "de usuarios, multas, libros y notificaciones."
    ),
    version="1.0.0",
    lifespan=lifespan
)


def convertir_prestamo(row):
    return {
        "prestamo_id": row["prestamo_id"],
        "usuario_id": row["usuario_id"],
        "libro_id": row["libro_id"],
        "activo": bool(row["activo"])
    }


async def solicitar(
    client: httpx.AsyncClient,
    metodo: str,
    url: str,
    recurso: str,
    datos=None
):
    try:
        respuesta = await client.request(
            metodo,
            url,
            json=datos
        )
    except httpx.RequestError:
        raise HTTPException(
            status_code=503,
            detail=f"No se pudo comunicar con el servicio de {recurso}"
        )

    if respuesta.status_code == 404:
        raise HTTPException(
            status_code=404,
            detail=f"Recurso no encontrado en el servicio de {recurso}"
        )

    if respuesta.status_code == 400:
        raise HTTPException(
            status_code=400,
            detail=f"El servicio de {recurso} rechazó la operación"
        )

    if not respuesta.is_success:
        raise HTTPException(
            status_code=503,
            detail=(
                f"El servicio de {recurso} respondió con "
                f"HTTP {respuesta.status_code}"
            )
        )

    return respuesta


async def consultar(
    client: httpx.AsyncClient,
    url: str,
    recurso: str
):
    respuesta = await solicitar(client, "GET", url, recurso)

    try:
        datos = respuesta.json()
    except ValueError:
        raise HTTPException(
            status_code=503,
            detail=f"Respuesta JSON inválida del servicio de {recurso}"
        )

    if not isinstance(datos, dict):
        raise HTTPException(
            status_code=503,
            detail=f"Respuesta inesperada del servicio de {recurso}"
        )

    return datos


async def cambiar_disponibilidad(
    client: httpx.AsyncClient,
    libro_id: int,
    disponible: bool
):
    await solicitar(
        client,
        "PATCH",
        f"{LIBROS_URL}/{libro_id}/disponibilidad",
        "libros",
        {"disponible": disponible}
    )


async def compensar_disponibilidad(
    client: httpx.AsyncClient,
    libro_id: int,
    disponible: bool
):
    # Intenta deshacer el cambio remoto si falla la escritura local.
    try:
        await cambiar_disponibilidad(client, libro_id, disponible)
    except HTTPException:
        logger.exception(
            "No se pudo restaurar la disponibilidad del libro %s",
            libro_id
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "Falló el guardado y no se pudo restaurar la "
                "disponibilidad. Revisa el estado del libro."
            )
        )


async def enviar_notificacion_prestamo(
    destinatario: str,
    libro_id: int,
    prestamo_id: int
):
    datos = {
        "destinatario": destinatario,
        "asunto": "Préstamo registrado",
        "mensaje": (
            f"Tu préstamo {prestamo_id} del libro con ID "
            f"{libro_id} se registró correctamente."
        )
    }

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            respuesta = await client.post(
                NOTIFICACIONES_URL,
                json=datos
            )
            respuesta.raise_for_status()

    except httpx.HTTPError as error:
        # El préstamo ya fue registrado. Una falla de notificación
        # se informa en consola, sin cancelar el préstamo.
        logger.warning(
            "No se pudo notificar el préstamo %s: %s",
            prestamo_id,
            error
        )


@app.post(
    "/prestamos",
    status_code=status.HTTP_201_CREATED,
    summary="Registrar un préstamo",
    description=(
        "Valida usuario, sanciones, límite de tres préstamos activos "
        "y disponibilidad del libro. Ocupa el libro, registra el "
        "préstamo y solicita una notificación en segundo plano."
    ),
    tags=["Préstamos"],
    responses={
        400: {"description": "Incumplimiento de una regla de negocio"},
        404: {"description": "Usuario o libro no encontrado"},
        503: {"description": "Servicio o base de datos no disponible"}
    }
)
async def crear_prestamo(
    datos: PrestamoCreate,
    background_tasks: BackgroundTasks
):
    async with app.state.operaciones:
        async with httpx.AsyncClient(timeout=5.0) as client:

            # 1. Verificar que exista el usuario.
            usuario = await consultar(
                client,
                f"{USUARIOS_URL}/{datos.usuario_id}",
                "usuarios"
            )

            # 2. Verificar multas pendientes.
            sanciones = await consultar(
                client,
                f"{SANCIONES_URL}/usuario/{datos.usuario_id}/estatus",
                "multas"
            )

            if not isinstance(sanciones.get("bloqueado"), bool):
                raise HTTPException(
                    status_code=503,
                    detail="El servicio de multas no devolvió un estado válido"
                )

            if sanciones["bloqueado"]:
                raise HTTPException(
                    status_code=400,
                    detail="El usuario tiene multas pendientes de pago"
                )

            # 3. Verificar el límite de préstamos activos.
            with get_db() as conn:
                cantidad = conn.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM prestamos
                    WHERE usuario_id = ? AND activo = 1
                    """,
                    (datos.usuario_id,)
                ).fetchone()["total"]

            if cantidad >= 3:
                raise HTTPException(
                    status_code=400,
                    detail="El usuario ya tiene tres préstamos activos"
                )

            # 4. Verificar existencia y disponibilidad del libro.
            libro = await consultar(
                client,
                f"{LIBROS_URL}/{datos.libro_id}",
                "libros"
            )

            if not isinstance(libro.get("disponible"), bool):
                raise HTTPException(
                    status_code=503,
                    detail="El servicio de libros no devolvió disponibilidad válida"
                )

            if not libro["disponible"]:
                raise HTTPException(
                    status_code=400,
                    detail="El libro no está disponible"
                )

            # Protección adicional ante datos desincronizados.
            with get_db() as conn:
                existente = conn.execute(
                    """
                    SELECT prestamo_id FROM prestamos
                    WHERE libro_id = ? AND activo = 1
                    """,
                    (datos.libro_id,)
                ).fetchone()

            if existente:
                raise HTTPException(
                    status_code=400,
                    detail="Este libro ya tiene un préstamo activo"
                )

            destinatario = usuario.get("email")

            if not isinstance(destinatario, str) or not destinatario.strip():
                raise HTTPException(
                    status_code=400,
                    detail="Actualiza el correo del usuario antes de solicitar el préstamo"
                )

            # 5. Ocupar el libro.
            await cambiar_disponibilidad(
                client,
                datos.libro_id,
                False
            )

            # 6. Guardar el préstamo.
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

            except sqlite3.Error:
                logger.exception("Error al guardar el préstamo")

                await compensar_disponibilidad(
                    client,
                    datos.libro_id,
                    True
                )

                raise HTTPException(
                    status_code=503,
                    detail="No se pudo guardar el préstamo"
                )

            # 7. Notificar después de enviar la respuesta al cliente.
            background_tasks.add_task(
                enviar_notificacion_prestamo,
                destinatario=destinatario,
                libro_id=datos.libro_id,
                prestamo_id=prestamo_id
            )

    return {
        "prestamo_id": prestamo_id,
        "usuario_id": datos.usuario_id,
        "libro_id": datos.libro_id,
        "activo": True
    }


@app.patch(
    "/prestamos/{prestamo_id}/devolver",
    summary="Registrar una devolución",
    description=(
        "Libera el libro en el servicio de libros y marca el préstamo "
        "como inactivo. Rechaza una segunda devolución."
    ),
    tags=["Préstamos"],
    responses={
        400: {"description": "El préstamo ya fue devuelto"},
        404: {"description": "Préstamo o libro no encontrado"},
        503: {"description": "Servicio o base de datos no disponible"}
    }
)
async def devolver_libro(prestamo_id: int):
    async with app.state.operaciones:
        with get_db() as conn:
            prestamo = conn.execute(
                "SELECT * FROM prestamos WHERE prestamo_id = ?",
                (prestamo_id,)
            ).fetchone()

        if prestamo is None:
            raise HTTPException(
                status_code=404,
                detail="Préstamo no encontrado"
            )

        if not prestamo["activo"]:
            raise HTTPException(
                status_code=400,
                detail="El libro ya fue devuelto"
            )

        async with httpx.AsyncClient(timeout=5.0) as client:
            # Liberar el libro antes de confirmar la devolución local.
            await cambiar_disponibilidad(
                client,
                prestamo["libro_id"],
                True
            )

            try:
                with get_db() as conn:
                    conn.execute(
                        """
                        UPDATE prestamos
                        SET activo = 0
                        WHERE prestamo_id = ?
                        """,
                        (prestamo_id,)
                    )

            except sqlite3.Error:
                logger.exception("Error al guardar la devolución")

                await compensar_disponibilidad(
                    client,
                    prestamo["libro_id"],
                    False
                )

                raise HTTPException(
                    status_code=503,
                    detail="No se pudo guardar la devolución"
                )

    resultado = convertir_prestamo(prestamo)
    resultado["activo"] = False
    return resultado
