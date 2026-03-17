import sys
import os
import subprocess
import shlex


# All commands implemented as shell builtins
BUILTINS: set[str] = {"exit", "echo", "type", "pwd", "cd"}


def parse_redirects(parts: list[str]) -> tuple[list[str], str | None, str]:
    """Extract stdout redirection from token list.
    Returns (clean_args, output_file, mode) where mode is 'w' or 'a'."""
    clean: list[str] = []
    output_file: str | None = None
    mode: str = "w"  # default to overwrite

    i: int = 0
    while i < len(parts):
        if parts[i] == ">>" and i + 1 < len(parts):
            # Append mode redirection
            output_file = parts[i + 1]
            mode = "a"
            i += 2
        elif parts[i] in (">", "1>") and i + 1 < len(parts):
            # Overwrite mode redirection
            output_file = parts[i + 1]
            mode = "w"
            i += 2
        else:
            clean.append(parts[i])
            i += 1

    return clean, output_file, mode


def handle_command(command: str) -> None:
    """Parse and execute a shell command, or report it as invalid."""
    # shlex.split() handles quoting and backslash escaping
    parts: list[str] = shlex.split(command, posix=True)

    # Ignore empty input (user just pressed Enter)
    if not parts:
        return

    # Extract any stdout redirection from the token list
    parts, output_file, mode = parse_redirects(parts)

    # Open the output file if redirection was requested, else use real stdout
    out = open(output_file, mode) if output_file else None

    try:
        cmd: str = parts[0]
        args: list[str] = parts[1:]

        if cmd == "exit":
            # Use the provided exit code, default to 0 (success)
            code: int = int(args[0]) if args else 0
            sys.exit(code)

        elif cmd == "echo":
            # Print all arguments joined by a single space
            print(" ".join(args), file=out or sys.stdout)

        elif cmd == "type":
            # Report whether each argument is a builtin or an external program
            for arg in args:
                if arg in BUILTINS:
                    print(f"{arg} is a shell builtin", file=out or sys.stdout)
                else:
                    external_path: str | None = find_in_path(arg)
                    if external_path:
                        print(f"{arg} is {external_path}", file=out or sys.stdout)
                    else:
                        print(f"{arg}: not found", file=out or sys.stdout)

        elif cmd == "pwd":
            # Print the current working directory
            print(os.getcwd(), file=out or sys.stdout)

        elif cmd == "cd":
            # Require exactly one argument
            if not args:
                print("cd: missing argument")
                return

            # Expand ~ to the user's home directory
            target: str = os.path.expanduser(args[0])

            try:
                os.chdir(target)
            except FileNotFoundError:
                print(f"cd: {target}: No such file or directory")
            except NotADirectoryError:
                print(f"cd: {target}: Not a directory")
            except PermissionError:
                print(f"cd: {target}: Permission denied")

        else:
            # Try to find and run the command as an external executable
            external_path: str | None = find_in_path(cmd)
            if external_path:
                # Pass the output file handle to subprocess if redirecting
                subprocess.run(
                    [external_path] + args,
                    stdout=out if out else None
                )
            else:
                print(f"{cmd}: command not found")

    finally:
        # Always close the file handle if we opened one
        if out:
            out.close()


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