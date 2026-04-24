from llm.client import generate


MODES = ["edit", "explain", "debug", "generate"]


def llm_router(text: str) -> str:
    messages = [
        {
            "role": "system",
            "content": "Classify intent: edit|explain|debug|generate. One word only."
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
            "content": "Classify scope: all|single. One word only."
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