def build_edit_prompt(mode, file_content, instruction):
    return [
        {
            "role": "system",
            "content":  """
You are a coding engine.

STRICT RULES:
- Output ONLY raw code
- DO NOT use markdown
- DO NOT use ``` or ```python
- DO NOT add explanations
- DO NOT add comments unless explicitly asked
- DO NOT wrap code in any formatting
- Output must be directly executable

If you include anything other than raw code, the response is invalid.
"""
        },
        {
            "role": "user",
            "content": f"""
FILE:
----------------
{file_content}
----------------
MODE: 
{mode}

INSTRUCTION:
{instruction}


Return ONLY the updated full file code if said in the mode else do as the mode says.
"""
        }
    ]