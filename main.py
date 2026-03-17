import sys


def handle_command(command: str) -> None:
    """Parse and execute a shell command, or report it as invalid."""
    parts: list[str] = command.split()

    # Ignore empty input (user just pressed Enter)
    if not parts:
        return

    cmd: str = parts[0]
    args: list[str] = parts[1:]

    if cmd == "exit":
        # Use the provided exit code, default to 0 (success)
        code: int = int(args[0]) if args else 0
        sys.exit(code)

    # Unknown command — report it
    print(f"{cmd}: command not found")


def main() -> None:
    """Main REPL loop — print prompt, read input, handle command."""
    while True:
        # Print the shell prompt (no newline, flush immediately)
        sys.stdout.write("$ ")
        sys.stdout.flush()

        # Read a line of input from the user
        command: str = input()

        handle_command(command)


if __name__ == "__main__":
    main()