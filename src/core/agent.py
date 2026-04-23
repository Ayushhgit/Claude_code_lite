import os
from utils.files import read_file
from utils.file_selector import pick_best_file
from core.prompt import build_edit_prompt
from core.router import detect_mode
from llm.groq_client import generate


def run(path, instruction):
    mode = detect_mode(instruction)

    # handle folder
    if os.path.isdir(path):
        selected_file = pick_best_file(path, instruction)

        if not selected_file:
            raise Exception("No valid code files found in folder")

        print(f"Selected file: {selected_file}")
        path = selected_file

    file_content = ""
    if mode != "generate":
        file_content = read_file(path)

    messages = build_edit_prompt(mode, file_content, instruction)
    result = generate(messages)

    return mode, result, path