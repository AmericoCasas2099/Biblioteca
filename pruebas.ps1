$ErrorActionPreference = "Stop"

$libros = "http://localhost:8001/libros"
$usuarios = "http://localhost:8002/usuarios"
$prestamos = "http://localhost:8003/prestamos"
$multas = "http://localhost:8005/multas"
$sanciones = "http://localhost:8005/sanciones"
$resenas = "http://localhost:8006/resenas"

$notificaciones = "http://localhost:8004/notificaciones/enviar"

function Peticion {
    param(
        [string]$Metodo,
        [string]$Url,
        [object]$Datos = $null,
        [int]$Esperado = 200
    )

    $entrada = [System.IO.Path]::GetTempFileName()
    $salida = [System.IO.Path]::GetTempFileName()

    try {
        $argumentos = @(
            "-sS",
            "--connect-timeout", "5",
            "--max-time", "20",
            "-X", $Metodo,
            $Url,
            "-o", $salida,
            "-w", "%{http_code}"
        )

        if ($null -ne $Datos) {
            $json = ConvertTo-Json -InputObject $Datos -Depth 10 -Compress
            $utf8 = New-Object System.Text.UTF8Encoding($false)

            [System.IO.File]::WriteAllText($entrada, $json, $utf8)

            $argumentos += @(
                "-H", "Content-Type: application/json",
                "--data-binary", "@$entrada"
            )
        }

        $codigo = & curl.exe @argumentos

        if ($LASTEXITCODE -ne 0) {
            throw "No se pudo conectar con $Url"
        }

        $contenido = Get-Content $salida -Raw -Encoding UTF8

        Write-Host "$Metodo $Url -> HTTP $codigo"
        if ($contenido) {
            Write-Host $contenido
        }

        if ([int]$codigo -ne $Esperado) {
            throw "Se esperaba HTTP $Esperado y se obtuvo $codigo"
        }

        if ($contenido) {
            return ConvertFrom-Json -InputObject $contenido
        }
    }
    finally {
        Remove-Item $entrada, $salida -Force -ErrorAction SilentlyContinue
    }
}

function Comprobar {
    param([bool]$Condicion, [string]$Mensaje)

    if (-not $Condicion) {
        throw $Mensaje
    }
}

try {
    # Correo distinto en cada ejecucion.
    $marca = [guid]::NewGuid().ToString("N")
    $correo = "prueba.$marca@example.com"

    Write-Host "`n1. Crear usuario"
    $usuario = Peticion POST $usuarios @{
        nombre = "Usuario de prueba"
        email = $correo
    } 201

    $usuarioId = $usuario.id

    Write-Host "`n2. Crear libro"
    $libro = Peticion POST $libros @{
        titulo = "Libro de prueba $marca"
        autor = "Autor de prueba"
    } 201

    $libroId = $libro.id

    Write-Host "`n3. Verificar que el usuario no tenga adeudos"
    $estado = Peticion GET "$sanciones/usuario/$usuarioId/estatus"

    Comprobar ($estado.bloqueado -eq $false) `
        "Un usuario sin multas no debe estar bloqueado."

    Write-Host "`n4. Asignar una multa"
    $multa = Peticion POST $multas @{
        usuario_id = $usuarioId
        monto = 50
        motivo = "Multa de prueba"
    } 201

    $multaId = $multa.multa_id

    Write-Host "`n5. Verificar el bloqueo por multa"
    $estado = Peticion GET "$sanciones/usuario/$usuarioId/estatus"

    Comprobar ($estado.bloqueado -eq $true) `
        "El usuario debe estar bloqueado."

    Comprobar ($estado.total_adeudado -eq 50) `
        "El adeudo debe ser de 50."

    Write-Host "`n6. Intentar prestar con multa: debe devolver 400"
    $null = Peticion POST $prestamos @{
        usuario_id = $usuarioId
        libro_id = $libroId
    } 400

    Write-Host "`n7. Pagar la multa"
    $null = Peticion PATCH "$multas/$multaId/pagar"

    $estado = Peticion GET "$sanciones/usuario/$usuarioId/estatus"

    Comprobar ($estado.bloqueado -eq $false) `
        "El usuario debe quedar desbloqueado."

    Comprobar ($estado.total_adeudado -eq 0) `
        "El adeudo debe quedar en cero."

    Write-Host "`n8. Crear el prestamo"
    $prestamo = Peticion POST $prestamos @{
        usuario_id = $usuarioId
        libro_id = $libroId
    } 201

    $prestamoId = $prestamo.prestamo_id

    Write-Host "`n9. Verificar que el libro este ocupado"
    $libro = Peticion GET "$libros/$libroId"

    Comprobar ($libro.disponible -eq $false) `
        "El prestamo debe cambiar la disponibilidad a false."

    Write-Host "`n10. Intentar eliminar el libro prestado: debe devolver 400"
    $null = Peticion DELETE "$libros/$libroId" $null 400

    Write-Host "`n11. Registrar una resena"
    $null = Peticion POST $resenas @{
        libro_id = $libroId
        usuario_id = $usuarioId
        calificacion = 5
        comentario = "Resena de prueba"
    } 201

    Write-Host "`n12. Consultar las resenas"
    $null = Peticion GET "$resenas/libro/$libroId"

    Write-Host "`n13. Probar directamente las notificaciones"
    $null = Peticion POST $notificaciones @{
        destinatario = $correo
        asunto = "Prueba de biblioteca"
        mensaje = "Notificacion de prueba"
    } 200

    Write-Host "`n14. Devolver el libro"
    $devolucion = Peticion PATCH "$prestamos/$prestamoId/devolver"

    Comprobar ($devolucion.activo -eq $false) `
        "El prestamo debe quedar inactivo."

    Write-Host "`n15. Verificar que el libro este disponible"
    $libro = Peticion GET "$libros/$libroId"

    Comprobar ($libro.disponible -eq $true) `
        "La devolucion debe liberar el libro."

    Write-Host "`nPRUEBAS COMPLETADAS" -ForegroundColor Green
    exit 0
}
catch {
    Write-Host "`nPRUEBA FALLIDA: $($_.Exception.Message)" `
        -ForegroundColor Red
    exit 1
}