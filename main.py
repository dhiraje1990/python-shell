import sys
import os
import subprocess
import shlex
import readline


# All commands implemented as shell builtins
BUILTINS: set[str] = {"exit", "echo", "type", "pwd", "cd"}


def get_path_executables() -> set[str]:
    """Return all executable names found in PATH directories."""
    executables: set[str] = set()
    path_dirs: list[str] = os.environ.get("PATH", "").split(os.pathsep)

    for directory in path_dirs:
        try:
            for name in os.listdir(directory):
                full_path: str = os.path.join(directory, name)
                if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                    executables.add(name)
        except PermissionError:
            # Skip directories we cannot read
            pass

    return executables


# Cache all completions at startup so Tab response is instant
ALL_COMPLETIONS: set[str] = set()


def build_completions() -> None:
    """Populate ALL_COMPLETIONS with builtins and PATH executables."""
    global ALL_COMPLETIONS
    ALL_COMPLETIONS = BUILTINS | get_path_executables()


def display_matches(substitution: str, matches: list[str], longest_match_length: int) -> None:
    """Display all matches on a new line when there are multiple completions."""
    line_buffer: str = readline.get_line_buffer()
    prompt: str = "$ "

    # Erase the current line (readline already drew "$ <typed text>" on screen)
    # chr(13) = carriage return, moves cursor to start of line without newline
    erase: str = chr(13) + " " * (len(prompt) + len(line_buffer)) + chr(13)
    sys.stdout.write(erase)

    # Print matches followed by a newline
    sys.stdout.write("  ".join(sorted(matches)) + chr(10))

    # Reprint only the prompt — readline will redraw the buffer itself
    sys.stdout.write(prompt)
    sys.stdout.flush()

def completer(text: str, state: int) -> str | None:
    """Readline completer — suggests builtins and PATH executables matching text."""
    # Filter cached completions to those starting with the text typed so far
    matches: list[str] = sorted(c for c in ALL_COMPLETIONS if c.startswith(text))

    # If no matches, ring the bell on the first state call to indicate no completions
    if not matches:
        if state == 0:
            sys.stdout.write("")
            sys.stdout.flush()
        return None

    # readline calls this repeatedly with increasing state until None is returned
    return matches[state] if state < len(matches) else None


def parse_redirects(parts: list[str]) -> tuple[list[str], str | None, str, str | None, str]:
    """Extract stdout and stderr redirection from token list.
    Returns (clean_args, stdout_file, stdout_mode, stderr_file, stderr_mode)."""
    clean: list[str] = []
    stdout_file: str | None = None
    stdout_mode: str = "w"
    stderr_file: str | None = None
    stderr_mode: str = "w"

    i: int = 0
    while i < len(parts):
        if parts[i] == ">>" and i + 1 < len(parts):
            # Append stdout
            stdout_file = parts[i + 1]
            stdout_mode = "a"
            i += 2
        elif parts[i] in (">", "1>") and i + 1 < len(parts):
            # Overwrite stdout
            stdout_file = parts[i + 1]
            stdout_mode = "w"
            i += 2
        elif parts[i] == "2>>" and i + 1 < len(parts):
            # Append stderr
            stderr_file = parts[i + 1]
            stderr_mode = "a"
            i += 2
        elif parts[i] == "2>" and i + 1 < len(parts):
            # Overwrite stderr
            stderr_file = parts[i + 1]
            stderr_mode = "w"
            i += 2
        else:
            clean.append(parts[i])
            i += 1

    return clean, stdout_file, stdout_mode, stderr_file, stderr_mode


def handle_command(command: str) -> None:
    """Parse and execute a shell command, or report it as invalid."""
    # shlex.split() handles quoting and backslash escaping
    parts: list[str] = shlex.split(command, posix=True)

    # Ignore empty input (user just pressed Enter)
    if not parts:
        return

    # Extract any stdout/stderr redirection from the token list
    parts, stdout_file, stdout_mode, stderr_file, stderr_mode = parse_redirects(parts)

    # Open file handles for redirection, or fall back to real stdout/stderr
    out = open(stdout_file, stdout_mode) if stdout_file else None
    err = open(stderr_file, stderr_mode) if stderr_file else None

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
                        # "not found" is an error, so it goes to stderr
                        print(f"{arg}: not found", file=err or sys.stderr)

        elif cmd == "pwd":
            # Print the current working directory
            print(os.getcwd(), file=out or sys.stdout)

        elif cmd == "cd":
            # Require exactly one argument
            if not args:
                print("cd: missing argument", file=err or sys.stderr)
                return

            # Expand ~ to the user's home directory
            target: str = os.path.expanduser(args[0])

            try:
                os.chdir(target)
            except FileNotFoundError:
                print(f"cd: {target}: No such file or directory", file=err or sys.stderr)
            except NotADirectoryError:
                print(f"cd: {target}: Not a directory", file=err or sys.stderr)
            except PermissionError:
                print(f"cd: {target}: Permission denied", file=err or sys.stderr)

        else:
            # Try to find and run the command as an external executable
            external_path: str | None = find_in_path(cmd)
            if external_path:
                subprocess.run(
                    [external_path] + args,
                    stdout=out if out else None,
                    stderr=err if err else None,
                )
            else:
                # Unknown command is an error, so it goes to stderr
                print(f"{cmd}: command not found", file=err or sys.stderr)

    finally:
        # Always close file handles if we opened them
        if out:
            out.close()
        if err:
            err.close()


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
    # Build the completion cache once at startup
    build_completions()

    # Register the completer and set tab as the completion key
    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")

    # Register the display hook for showing multiple matches
    readline.set_completion_display_matches_hook(display_matches)

    while True:
        # Print the shell prompt (no newline, flush immediately)
        sys.stdout.write("$ ")
        sys.stdout.flush()

        # Read a line of input from the user
        command: str = input()

        handle_command(command)


if __name__ == "__main__":
    main()