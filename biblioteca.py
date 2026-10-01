from enum import Enum
from typing import Dict, List, Optional
from fastapi import Body, FastAPI, HTTPException, Path, Query, status
from pydantic import BaseModel, ConfigDict, Field


# --- 1. Contratos de servicio y esquemas ---

class Genre(str, Enum):
    """Géneros de libros permitidos para la validación del esquema y desplegables de Swagger."""
    FICTION = "Ficción"
    NON_FICTION = "No ficción"
    SCIENCE_FICTION = "Ciencia ficción"
    FANTASY = "Fantasía"
    MYSTERY = "Misterio"
    BIOGRAPHY = "Biografía"
    TERROR = "Terror"


class BookBase(BaseModel):
    """Esquema base que define los atributos comunes de un libro."""
    title: str = Field(..., min_length=1, max_length=150,
                       examples=["Clean Architecture"])
    author: str = Field(..., min_length=1, max_length=100,
                        examples=["Robert C. Martin"])
    year: int = Field(..., ge=1000, le=2100, examples=[2017])
    isbn: str = Field(..., min_length=10, max_length=17,
                      examples=["978-0134494166"])
    genre: Genre = Field(..., examples=[Genre.NON_FICTION])


class BookCreate(BookBase):
    """Contrato de entrada para registrar un nuevo libro."""
    pass


class BookUpdate(BaseModel):
    """Contrato de entrada para actualizar la información de un libro (todos los campos son opcionales)."""
    title: Optional[str] = Field(None, min_length=1, max_length=150, examples=[
                                 "Clean Architecture (2da Edición)"])
    author: Optional[str] = Field(
        None, min_length=1, max_length=100, examples=["Robert C. Martin"])
    year: Optional[int] = Field(None, ge=1000, le=2100, examples=[2018])
    isbn: Optional[str] = Field(
        None, min_length=10, max_length=17, examples=["978-0134494166"])
    genre: Optional[Genre] = Field(None, examples=[Genre.NON_FICTION])


class BookResponse(BookBase):
    """Contrato de salida devuelto a los clientes."""
    id: int = Field(..., description="Identificador único autoincrementable", examples=[
                    1])

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": 1,
                "title": "Clean Architecture",
                "author": "Robert C. Martin",
                "year": 2017,
                "isbn": "978-0134494166",
                "genre": "No ficción"
            }
        }
    )


# --- 2. Almacenamiento en memoria e inicialización de la aplicación ---

app = FastAPI(
    title="API del Servicio de Biblioteca",
    description="Demostración simple de Arquitectura Orientada a Servicios (SOA) que ilustra contratos de API y documentación.",
    version="2.0.0",
    author="Arturo Barajas"
)

# Diccionario de almacenamiento en memoria: {book_id: BookResponse}
db: Dict[int, BookResponse] = {}
id_counter: int = 1


# --- 3. Endpoints (Operaciones del servicio) ---

@app.post(
    "/libros",
    response_model=BookResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Libros"],
    summary="Agregar un nuevo libro",
    description="Registra un nuevo libro en el catálogo con un ID autoincrementable."
)
def create_book(book_in: BookCreate) -> BookResponse:
    global id_counter

    # Regla de dominio: verificar si el ISBN ya existe
    if any(b.isbn == book_in.isbn for b in db.values()):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ya existe un libro registrado con el ISBN '{book_in.isbn}'."
        )

    new_book = BookResponse(id=id_counter, **book_in.model_dump())
    db[id_counter] = new_book
    id_counter += 1
    return new_book


@app.get(
    "/libros",
    response_model=List[BookResponse],
    status_code=status.HTTP_200_OK,
    tags=["Libros"],
    summary="Listar o filtrar libros",
    description="Obtiene todos los libros o aplica filtros de búsqueda insensibles a mayúsculas y minúsculas."
)
def get_books(
    title: Optional[str] = Query(
        None, description="Filtrar por título (coincidencia parcial)"),
    author: Optional[str] = Query(
        None, description="Filtrar por autor (coincidencia parcial)"),
    isbn: Optional[str] = Query(None, description="Filtrar por ISBN exacto"),
    genre: Optional[Genre] = Query(None, description="Filtrar por género")
) -> List[BookResponse]:
    # Lógica de filtrado en una sola pasada
    return [
        book for book in db.values()
        if (title is None or title.lower() in book.title.lower())
        and (author is None or author.lower() in book.author.lower())
        and (isbn is None or book.isbn == isbn)
        and (genre is None or book.genre == genre)
    ]


@app.get(
    "/libros/{book_id}",
    response_model=BookResponse,
    status_code=status.HTTP_200_OK,
    tags=["Libros"],
    summary="Obtener un libro por ID"
)
def get_book_by_id(
    book_id: int = Path(..., ge=1, description="El ID del libro a consultar")
) -> BookResponse:
    if book_id not in db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró el libro con el ID {book_id}."
        )
    return db[book_id]


@app.patch(
    "/libros/{book_id}",
    response_model=BookResponse,
    status_code=status.HTTP_200_OK,
    tags=["Libros"],
    summary="Actualizar detalles de un libro",
    description="Actualiza parcialmente uno o más campos de un libro existente."
)
def update_book(
    book_id: int = Path(..., ge=1, description="El ID del libro a actualizar"),
    book_update: BookUpdate = Body(...)
) -> BookResponse:
    if book_id not in db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró el libro con el ID {book_id}."
        )

    stored_book = db[book_id]
    update_data = book_update.model_dump(exclude_unset=True)

    # Validar la unicidad del ISBN al actualizar
    if "isbn" in update_data:
        new_isbn = update_data["isbn"]
        if any(b.isbn == new_isbn and b.id != book_id for b in db.values()):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Ya existe un libro registrado con el ISBN '{new_isbn}'."
            )

    updated_book = stored_book.model_copy(update=update_data)
    db[book_id] = updated_book
    return updated_book


@app.delete(
    "/libros/{book_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["Libros"],
    summary="Eliminar un libro"
)
def delete_book(
    book_id: int = Path(..., ge=1, description="El ID del libro a eliminar")
):
    if book_id not in db:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No se encontró el libro con el ID {book_id}."
        )
    del db[book_id]
    return None
