import os

CODE_EXTENSIONS = [".py", ".js", ".ts", ".java", ".cpp"]


def get_all_files(folder_path):
    files = []
    for root, _, filenames in os.walk(folder_path):
        for f in filenames:
            if any(f.endswith(ext) for ext in CODE_EXTENSIONS):
                files.append(os.path.join(root, f))
    return files


def score_file(file_path, instruction):
    score = 0
    name = os.path.basename(file_path).lower()
    instruction = instruction.lower()

    # keyword match in filename
    for word in instruction.split():
        if word in name:
            score += 2

    # prioritize common entry files
    if "main" in name or "app" in name:
        score += 3

    return score


def pick_best_file(folder_path, instruction):
    files = get_all_files(folder_path)

    if not files:
        return None

    scored = [(f, score_file(f, instruction)) for f in files]
    scored.sort(key=lambda x: x[1], reverse=True)

    return scored[0][0]