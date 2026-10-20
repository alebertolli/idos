# OpenAPI Specification for IDOS

Este directorio contiene la especificación OpenAPI 3.0 para el sistema IDOS (Investment Decision Operating System).

## Estructura

- `openspec.yaml` - Archivo principal de especificación OpenAPI 3.0

## Uso

Para visualizar o interactuar con esta especificación:

1. Con herramientas como Swagger UI:
   ```bash
   # Instalar swagger-ui (opcional)
   npm install -g swagger-ui-dist
   
   # Ejecutar swagger-ui (requiere un servidor estático)
   npx serve . --no-clipboard
   ```

2. Con ReDoc:
   ```html
   <!DOCTYPE html>
   <html>
   <head>
     <title>IDOS API</title>
     <meta charset="utf-8"/>
     <meta name="viewport" content="width=device-width, initial-scale=1">
   </head>
   <body>
     <redoc spec-url="openspec.yaml"></redoc>
     <script src="https://cdn.jsdelivr.net/npm/redoc@2.0.0/bundles/redoc.standalone.js"> </script>
   </body>
   </html>
   ```

3. Con Redoc CLI para generar estático HTML:
   ```bash
   npx redoc-cli bundle openspec.yaml --output docs.html
   ```

## Generación de Código

Esta especificación puede ser utilizada para generar código cliente/servidor en múltiples lenguajes con herramientas como:

- OpenAPI Generator: https://openapi-generator.tech/
- Swagger Codegen: https://swagger.io/tools/swagger-codegen/

Ejemplo con OpenAPI Generator:
```bash
npm install @openapitools/openapi-generator-cli -g
openapi-generator-cli generate -i openspec.yaml -g typescript-angular -o ./client
```

## Validar la especificación

Puedes validar que el archivo `openspec.yaml` sea una especificación OpenAPI válida con:

```bash
# Con swagger-cli
npm install -g @swagger-api/swagger-cli
swagger-cli validate openspec.yaml

# Con prism (de stoplight)
npm install -g @stoplight/prism-cli
prism lint openspec.yaml
```

## Relación con el sistema IDOS

Esta especificación describe los endpoints que podrían estar disponibles en una versión futura del sistema IDOS que incluya una API REST. Actualmente, el sistema IDOS se interactúa principalmente a través de:

- Interfaz de línea de comandos (CLI)
- Archivos YAML en el sistema de archivos
- Eventos de GitHub Actions
- Notificaciones por Telegram/Email