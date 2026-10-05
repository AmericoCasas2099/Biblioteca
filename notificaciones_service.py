from datetime import datetime

from fastapi import FastAPI, status
from pydantic import BaseModel, Field, ConfigDict


app = FastAPI(
    title="Servicio de Notificaciones",
    description=(
        "Microservicio encargado de simular el envío de "
        "notificaciones y correos del sistema de biblioteca."
    ),
    version="1.0.0"
)


class NotificacionCreate(BaseModel):
    destinatario: str = Field(
        ...,
        description="Correo electrónico del destinatario",
        examples=["usuario@email.com"]
    )

    asunto: str = Field(
        ...,
        min_length=1,
        description="Asunto de la notificación",
        examples=["Préstamo registrado"]
    )

    mensaje: str = Field(
        ...,
        min_length=1,
        description="Contenido del mensaje",
        examples=["Tu préstamo se registró correctamente."]
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "destinatario": "usuario@email.com",
                "asunto": "Préstamo registrado",
                "mensaje": "Tu préstamo se registró correctamente."
            }
        }
    )


@app.get(
    "/",
    tags=["General"],
    summary="Verificar servicio",
    description="Permite comprobar que el servicio de notificaciones está activo."
)
def root():
    return {
        "servicio": "Notificaciones",
        "version": "v1",
        "estado": "activo"
    }


@app.post(
    "/api/v1/notificaciones/enviar",
    status_code=status.HTTP_201_CREATED,
    tags=["Notificaciones"],
    summary="Enviar notificación",
    description=(
        "Recibe los datos de una notificación y simula "
        "su envío mostrando la información en consola."
    )
)
def enviar_notificacion(notificacion: NotificacionCreate):

    fecha = datetime.now()

    print("\n==============================")
    print("      NUEVA NOTIFICACIÓN")
    print("==============================")
    print(f"Destinatario: {notificacion.destinatario}")
    print(f"Asunto: {notificacion.asunto}")
    print(f"Mensaje: {notificacion.mensaje}")
    print(f"Fecha: {fecha}")
    print("==============================\n")

    return {
        "message": "Notificación enviada correctamente",
        "destinatario": notificacion.destinatario,
        "asunto": notificacion.asunto,
        "fecha": fecha
    }
