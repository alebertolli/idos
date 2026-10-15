import yaml

with open('openspec.yaml', 'r') as f:
    spec = yaml.safe_load(f)

# Validar estructura basica
assert 'openapi' in spec, 'Falta openapi'
assert 'info' in spec, 'Falta info'
assert 'paths' in spec, 'Falta paths'
assert 'components' in spec, 'Falta components'

# Validar metodos HTTP validos
valid_methods = {'get', 'post', 'put', 'delete', 'patch', 'options', 'head'}
for path, methods in spec['paths'].items():
    for method in methods:
        assert method in valid_methods, 'Metodo invalido: ' + method

# Contar endpoints
endpoint_count = sum(len(methods) for methods in spec['paths'].values())
schema_count = len(spec.get('components', {}).get('schemas', {}))

print('Especificacion valida OK')
print('  - OpenAPI version:', spec['openapi'])
print('  - Endpoints:', endpoint_count)
print('  - Schemas:', schema_count)
print('  - Rutas:', list(spec['paths'].keys()))
print('  - Schemas:', list(spec['components']['schemas'].keys()))

# Mostrar resumen de cada endpoint
print()
print('Endpoints:')
for path, methods in spec['paths'].items():
    for method, details in methods.items():
        desc = details.get('description', '')
        print('  ' + method.upper().ljust(6) + ' ' + path + ' -> ' + desc)