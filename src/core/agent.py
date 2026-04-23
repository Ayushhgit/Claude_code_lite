import os
from utils.files import read_file
from utils.file_selector import llm_pick_file
from core.prompt import build_edit_prompt
from core.router import detect_mode
from llm.groq_client import generate


def run(path, instruction):
    mode = detect_mode(instruction)

    # Handle folder input
    if os.path.isdir(path):
        # get only python files
        files = [
            f for f in os.listdir(path)
            if f.endswith(".py")
        ]

        if not files:
            raise Exception("No Python files found in folder")

        # LLM picks file
        selected_file = llm_pick_file(files, instruction)

        # cleanup
        selected_file = selected_file.strip().replace("`", "")

        # validate output
        files_lower = [f.lower() for f in files]
        if selected_file.lower() not in files_lower:
            print("LLM returned invalid file, using fallback")
            selected_file = files[0]

        # rebuild correct path
        path = os.path.join(path, selected_file)

        print(f"Selected file: {path}")

    # Read file (if not generate mode)
    file_content = ""
    if mode != "generate":
        if not os.path.exists(path):
            raise FileNotFoundError(f"{path} does not exist")

        if os.path.isdir(path):
            raise IsADirectoryError(f"{path} is still a directory (unexpected)")

        file_content = read_file(path)

    # Build prompt
    messages = build_edit_prompt(mode, file_content, instruction)

    # Call LLM
    result = generate(messages)

    return mode, result, path