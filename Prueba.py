
from fastapi import FastAPI, requests
import pydantic
import uvicorn
import requests


app = FastAPI(
    title="Clima API",
    description="API para consultar el clima de diferentes ciudades.",
    version="1.0.2",
    contact={
        "name": "Américo Casas",
        "email": "goombarioxd@digiclin.com"
    }


)


@app.get("/")
def read_root():
    return {"message": "Bienvenido a la API de DIGICLIN"}


@app.get("/clima/{ciudad}/{clima}")
def read_clima(ciudad: str, clima: str):
    return {"message": f"El clima en {ciudad} es {clima}"}


@app.get("/pokemon/{nombre}")
def read_pokemon(nombre: str):
    response = requests.get(
        f"https://pokeapi.co/api/v2/pokemon/{nombre.lower()}")
    if response.status_code == 200:
        data = response.json()
        return {
            "nombre": data["name"],
            "id": data["id"],
            "altura": data["height"],
            "peso": data["weight"],
            "tipos": [tipo["type"]["name"] for tipo in data["types"]]
        }
    else:
        return {"error": "Pokémon no encontrado o inexistente."}
