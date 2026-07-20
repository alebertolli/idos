param(
    [string]$filePath = $args[0]
)

# Verificar si estamos en un repositorio git
if (-not (Test-Path ".git")) {
    Write-Host "No es un repositorio git, omitiendo commit automático" -ForegroundColor Yellow
    exit 0
}

# Verificar si hay cambios
$status = git status --porcelain
if (-not $status) {
    Write-Host "No hay cambios para commitear" -ForegroundColor Yellow
    exit 0
}

# Obtener el archivo modificado
$fileName = Split-Path $filePath -Leaf
$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$commitMessage = "auto-commit: $fileName - $timestamp"

try {
    git add "$filePath"
    git commit -m $commitMessage
    git push
    Write-Host "Commit automático realizado: $commitMessage" -ForegroundColor Green
} catch {
    Write-Warning "Error al hacer commit/push automático: $_"
    # No fallar el hook si falla el push
    exit 0
}