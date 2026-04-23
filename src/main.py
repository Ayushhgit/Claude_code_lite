from core.agent import run
from utils.files import write_file
import os
from dotenv import load_dotenv
load_dotenv()

def main():
    file_path = os.getenv("FOLDER_PATH")
    inst = input("What do you want to change?\n")

    mode, output, final_path = run(file_path, inst)
    print(f"\n[MODE: {mode.upper()}]")
    print(f"[FILE: {final_path}]\n")
    print(output)

    if mode in ["edit", "debug"]:
        save = input("\nSave changes? (y/n): ")
        if save.lower() == "y":
            write_file(final_path, output)
            print("Saved.")

if __name__ == "__main__":
    main()