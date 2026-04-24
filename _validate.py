"""Quick validation script to check tool schema <-> handler consistency."""
import sys, os, re, inspect
sys.path.insert(0, 'src')
os.environ['GROQ_API_KEY'] = 'test'
os.environ['MODEL'] = 'test'
os.environ['FOLDER_PATH'] = '.'

from core.tools import TOOLS_SCHEMA, execute_tool

# 1. Schema names
schema_names = sorted([t['function']['name'] for t in TOOLS_SCHEMA])
print(f"TOOLS_SCHEMA: {len(schema_names)} tools")
for n in schema_names:
    print(f"  {n}")

# 2. Handler names from execute_tool source
source = inspect.getsource(execute_tool)
handler_names = sorted(set(re.findall(r'tool_name\s*==\s*"(\w+)"', source)))
print(f"\nexecute_tool handlers: {len(handler_names)} tools")
for n in handler_names:
    print(f"  {n}")

# 3. Mismatch check
schema_set = set(schema_names)
handler_set = set(handler_names)
missing_handlers = schema_set - handler_set
missing_schemas = handler_set - schema_set
if missing_handlers:
    print(f"\n!! MISSING HANDLERS (schema but no executor): {missing_handlers}")
if missing_schemas:
    print(f"\n!! MISSING SCHEMAS (handler but no schema): {missing_schemas}")
if not missing_handlers and not missing_schemas:
    print(f"\n✓ Perfect match: all {len(schema_names)} tools wired correctly")
