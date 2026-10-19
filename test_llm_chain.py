from idos.ai.llm import LLMClient

client = LLMClient(
    provider='openrouter',
    api_key='',
    model='meta-llama/llama-3.3-70b-instruct:free',
    fallback_providers=[
        {'provider': 'groq', 'model': 'llama-3.3-70b-versatile'},
        {'provider': 'gemini', 'model': 'gemini-2.0-flash'},
    ],
)
print('=== Default provider ===')
print(f'  provider:   {client.provider}')
print(f'  model:      {client.model}')
print(f'  api_key:    {client.api_key!r}')
print(f'  fallbacks:  {len(client.fallback_providers)} entries')
for i, fb in enumerate(client.fallback_providers):
    print(f'    [{i}] {fb["provider"]}/{fb["model"]}')

resp = client.generate('Say hello in one word')
print(f'\n=== Result ===')
print(f'  success: {resp.success}')
print(f'  error:   {resp.error}')
print(f'  latency: {resp.latency_ms}ms')

client2 = LLMClient(provider='groq', api_key='', model='llama-3.3-70b-versatile')
resp2 = client2.generate('Say hello')
print(f'\n=== Groq direct (no key) ===')
print(f'  success: {resp2.success}')
print(f'  error:   {resp2.error}')

client3 = LLMClient(provider='gemini', api_key='', model='gemini-2.0-flash')
resp3 = client3.generate('Say hello')
print(f'\n=== Gemini direct (no key) ===')
print(f'  success: {resp3.success}')
print(f'  error:   {resp3.error}')
