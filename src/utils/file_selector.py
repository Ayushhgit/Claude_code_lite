from llm.groq_client import generate


def llm_pick_file(files, instruction):
    file_list = "\n".join(files)

    messages = [
        {
            "role": "system",
            "content": """
You are a codebase assistant.

Pick the SINGLE most relevant file.

Return ONLY the file name from the list.
Do NOT return a path.
Do NOT explain.
"""
        },
        {
            "role": "user",
            "content": f"""
FILES:
{file_list}

INSTRUCTION:
{instruction}
"""
        }
    ]

    result = generate(messages).strip()

    # 🧹 cleanup (important)
    result = result.replace("`", "").strip()

    return result