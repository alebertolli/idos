import json, re

# Simulate what the LLM returned (markdown fenced JSON)
content = """```json
{
  "clasificacion_oportunidad": {
    "categoria": "compounder",
    "justificacion": "test"
  }
}
```"""

cleaned = content.strip()
print("Starts with backtick:", cleaned.startswith("```"))

if cleaned.startswith("```"):
    for line in cleaned.split("\n"):
        if line.strip().startswith("{"):
            cleaned = line.strip()
            print("Found JSON line, cleaned =", repr(cleaned[:80]))
            break
    else:
        cleaned = cleaned.replace("```json", "").replace("```", "").strip()
        print("Else branch, cleaned =", repr(cleaned[:80]))

print()
print("Trying json.loads...")
try:
    print("OK:", json.loads(cleaned))
except json.JSONDecodeError as e:
    print("FAIL:", e)
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        print("Fallback matched:", repr(match.group()[:80]))
        try:
            print("Fallback OK:", json.loads(match.group()))
        except json.JSONDecodeError as e2:
            print("Fallback FAIL:", e2)

# Test 2: SelfHealer
from idos.resilience.self_healing import SelfHealer
h = SelfHealer()
r = h.parse_with_healing(content)
print("\nSelfHealer result:", r)
