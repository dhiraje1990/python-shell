import sys
import os


# All commands implemented as shell builtins
BUILTINS: set[str] = {"exit", "echo", "type"}


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

    elif cmd == "echo":
        # Print all arguments joined by a single space
        print(" ".join(args))

    elif cmd == "type":
        # Report whether each argument is a builtin or an external program
        for arg in args:
            if arg in BUILTINS:
                print(f"{arg} is a shell builtin")
            else:
                # Search each directory in PATH for the command
                external_path: str | None = find_in_path(arg)
                if external_path:
                    print(f"{arg} is {external_path}")
                else:
                    print(f"{arg}: not found")

    else:
        # Unknown command — report it
        print(f"{cmd}: command not found")


def find_in_path(cmd: str) -> str | None:
    """Search PATH directories for an executable named cmd.
    Returns the full path if found, otherwise None."""
    path_dirs: list[str] = os.environ.get("PATH", "").split(os.pathsep)

    for directory in path_dirs:
        full_path: str = os.path.join(directory, cmd)
        if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
            return full_path

    return None


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