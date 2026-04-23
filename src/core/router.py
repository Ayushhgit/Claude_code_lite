from llm.groq_client import generate


MODES = ["edit", "explain", "debug", "generate"]


# def rule_based_router(text: str) -> str | None:
#     t = text.lower()

#     if any(k in t for k in ["explain", "what does", "how does"]):
#         return "explain"

#     if any(k in t for k in ["bug", "fix", "error", "not working", "issue"]):
#         return "debug"

#     if any(k in t for k in ["create", "generate", "build", "from scratch"]):
#         return "generate"

#     if any(k in t for k in ["add", "update", "modify", "change"]):
#         return "edit"

#     return None

def llm_router(text: str) -> str:
    messages = [
        {
            "role": "system",
            "content": """
Classify the user's intent into EXACTLY one of these modes:
- edit
- explain
- debug
- generate

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

def detect_mode(text: str) -> str:
    # Step 1: try fast rules
    # mode = rule_based_router(text)

    # if mode:
    #     return mode

    # Step 2: fallback to LLM
    return llm_router(text)