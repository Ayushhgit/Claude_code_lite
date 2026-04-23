from utils.files import read_file
from core.prompt import build_edit_prompt
from llm.groq_client import generate

def run_edit(file_path, inst):
    file_content = read_file(file_path)
    messages = build_edit_prompt(file_content, inst)
    result = generate(messages)
    return result