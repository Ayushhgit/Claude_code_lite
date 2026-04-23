from core.agent import run_edit
from utils.files import write_file
import os
from dotenv import load_dotenv
load_dotenv()

def main():
    file_path = os.getenv("FOLDER_PATH")
    inst = input("What do you want to change?\n")

    updated_code = run_edit(file_path, inst)
    print("\n--- UPDATED CODE ---\n")
    print(updated_code)

    save = input("Do you want to save it? (y/n): ")
    if save.lower() == "y":
        write_file(file_path, updated_code)
        print("saved.")

if __name__ == "__main__":
    main()