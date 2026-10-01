from fastapi import FastAPI, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

app = FastAPI(
    title="Servicio de Usuarios de Biblioteca",
    description="API RESTful para la gestión de usuarios de la biblioteca con almacenamiento en memoria.",
    version="1.0.0"
)

# 1. Esquemas de Pydantic (Contratos y Validación)
class UserBase(BaseModel):
    name: str = Field(..., min_length=1, description="Nombre completo del usuario")
    email: EmailStr = Field(..., description="Dirección de correo electrónico válida")
    phone: str = Field(..., pattern=r"^\d{10}$", description="Número telefónico de exactamente 10 dígitos numéricos")

class UserCreate(UserBase):
    pass

class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, description="Nombre completo del usuario")
    email: EmailStr | None = Field(default=None, description="Dirección de correo electrónico válida")
    phone: str | None = Field(default=None, pattern=r"^\d{10}$", description="Número telefónico de exactamente 10 dígitos numéricos")

class UserResponse(UserBase):
    user_id: int = Field(..., description="Identificador único autoincrementable")

# 2. Almacenamiento en memoria (Simulación de Base de Datos)
db_users: dict[int, UserResponse] = {
    1: UserResponse(user_id=1, name="Alice Smith", email="alice@ejemplo.com", phone="5551234567"),
    2: UserResponse(user_id=2, name="Bob Jones", email="bob@ejemplo.com", phone="5559876543"),
}
next_user_id: int = 3

# 3. Endpoints REST
@app.get(
    "/users", 
    response_model=list[UserResponse],
    summary="Obtener todos los usuarios",
    description="Retorna la lista completa de usuarios registrados en el sistema."
)
def get_users():
    return list(db_users.values())

@app.get(
    "/users/{user_id}", 
    response_model=UserResponse,
    summary="Obtener un usuario por ID",
    description="Busca y retorna un usuario específico mediante su ID único."
)
def get_user(user_id: int):
    if user_id not in db_users:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"El usuario con el ID {user_id} no fue encontrado."
        )
    return db_users[user_id]

@app.post(
    "/users", 
    response_model=UserResponse, 
    status_code=status.HTTP_201_CREATED,
    summary="Crear un nuevo usuario",
    description="Registra un nuevo usuario validando que el correo y teléfono cumplan con el formato requerido."
)
def create_user(payload: UserCreate):
    global next_user_id
    
    new_user = UserResponse(
        user_id=next_user_id,
        name=payload.name,
        email=payload.email,
        phone=payload.phone
    )
    
    db_users[next_user_id] = new_user
    next_user_id += 1
    
    return new_user

@app.put(
    "/users/{user_id}", 
    response_model=UserResponse,
    summary="Actualizar un usuario existente",
    description="Permite la actualización parcial o total de los datos de un usuario especificado por su ID."
)
def update_user(user_id: int, payload: UserUpdate):
    if user_id not in db_users:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"El usuario con el ID {user_id} no fue encontrado."
        )
    
    existing_user = db_users[user_id]
    
    # Lógica para actualización parcial
    updated_data = payload.model_dump(exclude_unset=True)
    stored_data = existing_user.model_dump()
    stored_data.update(updated_data)
    
    updated_user = UserResponse(**stored_data)
    db_users[user_id] = updated_user
    
    return updated_user

@app.delete(
    "/users/{user_id}", 
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar un usuario",
    description="Elimina permanentemente del sistema al usuario correspondiente al ID dado."
)
def delete_user(user_id: int):
    if user_id not in db_users:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail=f"El usuario con el ID {user_id} no fue encontrado."
        )
    del db_users[user_id]
    return None