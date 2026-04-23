from llm.groq_client import generate


MODES = ["edit", "explain", "debug", "generate"]


def llm_router(text: str) -> str:
    messages = [
        {
            "role": "system",
            "content": """
Classify the user's intent into EXACTLY one of these modes:
- edit (modifying existing code, adding new features to existing files)
- explain (explaining how code works)
- debug (fixing bugs, errors, or issues)
- generate (creating completely new files from scratch)

Return ONLY one word from the list. No explanation.
"""
        },
        {
            "role": "user",
            "content": text
        }
    ]

    result = generate(messages).strip().lower()

    if result not in MODES:
        return "edit"  

    return result

def detect_scope(text: str) -> str:
    messages = [
        {
            "role": "system",
            "content": """
Classify the scope of the user's instruction into EXACTLY one of these scopes:
- all (if the user wants to apply the change to all files, the entire project, every file, etc.)
- single (if the user wants to apply the change to a specific file, or if no scope is explicitly mentioned)

Return ONLY one word from the list. No explanation.
"""
        },
        {
            "role": "user",
            "content": text
        }
    ]

    result = generate(messages).strip().lower()

    if result not in ["all", "single"]:
        return "single"

    return result

def detect_mode(text: str) -> str:
    return llm_router(text)