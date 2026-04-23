from core.agent import init_messages, run_turn
import os
from dotenv import load_dotenv

load_dotenv()


def main():
    path = os.getenv("FOLDER_PATH")

    if not path:
        print("FOLDER_PATH not set in .env")
        return

    messages = init_messages(path)
    
    print(f"Agent initialized in {path}. Type 'exit' or 'quit' to close.")

    while True:
        try:
            instruction = input("\nWhat do you want to change?\n> ")
        except (KeyboardInterrupt, EOFError):
            print("\nExiting...")
            break
            
        if not instruction.strip():
            continue
            
        if instruction.strip().lower() in ["exit", "quit"]:
            print("Exiting...")
            break

        print("\n[AGENT IS THINKING AND ACTING...]\n")
        output = run_turn(messages, instruction)

        print(f"\n[AGENT FINISHED]\n{output}")


if __name__ == "__main__":
    main()