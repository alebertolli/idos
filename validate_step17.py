"""Step 17: Prompts validation"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "idos-core"))

from idos.ai.prompts import PromptRegistry

print("="*60, "\nSTEP 17: Prompts")

prompts_dir = Path("idos-config/prompts")
registry = PromptRegistry(prompts_dir=str(prompts_dir))

print(f"Total prompts loaded: {registry.count()}")

all_templates = registry.all()
categories = set()
for tmpl in all_templates:
    cat = tmpl.category
    categories.add(cat)
    assert tmpl.system_prompt, f"Missing system_prompt in {tmpl.name}"
    assert tmpl.user_prompt, f"Missing user_prompt in {tmpl.name}"
    print(f"  {tmpl.name} [{cat}] — valid")

print(f"\nCategories: {categories}")

print(f"\nSTEP 17 COMPLETE: {registry.count()} prompts OK")
