import json, re

content = "```json\n{\n  \"key\": \"value\"\n}\n```"

cleaned = content.strip()
cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
cleaned = re.sub(r"\s*```$", "", cleaned)
cleaned = cleaned.strip()

parsed = json.loads(cleaned)
print("OK:", parsed)

# test nested JSON
content2 = '```json\n{"a": {"b": "c"}}\n```'
cleaned2 = re.sub(r"^```(?:json)?\s*", "", content2.strip())
cleaned2 = re.sub(r"\s*```$", "", cleaned2)
parsed2 = json.loads(cleaned2)
print("OK2:", parsed2)

# test no fence
content3 = '{"x": 1}'
cleaned3 = re.sub(r"^```(?:json)?\s*", "", content3.strip())
cleaned3 = re.sub(r"\s*```$", "", cleaned3)
parsed3 = json.loads(cleaned3)
print("OK3:", parsed3)
