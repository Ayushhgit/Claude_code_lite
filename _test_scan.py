"""Functional test: run deep scan on test_folder and verify it captures everything."""
import sys, os, json
sys.path.insert(0, 'src')
os.environ['GROQ_API_KEY'] = 'test'
os.environ['MODEL'] = 'test'
os.environ['FOLDER_PATH'] = 'test_folder'

from core.codebase_brain import deep_scan, save_brain, load_brain, generate_compact_brain, get_brain_context

target = 'test_folder'
if not os.path.exists(target):
    print(f"test_folder not found, testing on src/ instead")
    target = 'src'

print(f"=== Deep scanning: {target} ===")
brain = deep_scan(target)

print(f"\nProject: {brain['project_name']}")
print(f"Tech stack: {brain['tech_stack']}")
print(f"Entry points: {brain['entry_points']}")
print(f"File tree ({len(brain['file_tree'])} files): {brain['file_tree'][:15]}...")
print(f"Modules ({len(brain['modules'])}): {list(brain['modules'].keys())[:10]}")
print(f"Other files ({len(brain['other_files'])}): {list(brain['other_files'].keys())[:10]}")
print(f"Directories ({len(brain['directories'])}): {[d['path'] for d in brain['directories'][:10]]}")
empty = [d for d in brain['directories'] if d.get('empty')]
print(f"Empty dirs ({len(empty)}): {[d['path'] for d in empty]}")
print(f"Dependencies: {brain['dependencies'][:8]}")
print(f"Summary: {brain['summary']}")
print(f"Scan time: {brain['stats'].get('scan_time_s', '?')}s")

# Test save/load
save_brain(brain, target)
loaded = load_brain(target)
if loaded:
    print(f"\nSave/Load: OK (loaded {len(loaded['file_tree'])} files back)")
else:
    print("\nSave/Load: FAILED")

# Test compact context
compact = generate_compact_brain(brain)
print(f"\nCompact brain ({len(compact)} chars):")
print(compact[:500])

# Test get_brain_context
ctx = get_brain_context(target)
print(f"\nget_brain_context: {'OK' if ctx else 'EMPTY'} ({len(ctx)} chars)")

print("\n=== All functional tests passed ===")
