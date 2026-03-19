import sys
import os
import subprocess
import shlex
import readline


# All commands implemented as shell builtins
BUILTINS: set[str] = {"exit", "echo", "type", "pwd", "cd", "history"}


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


def longest_common_prefix(strings: list[str]) -> str:
    """Return the longest common prefix shared by all strings in the list."""
    if not strings:
        return ""
    prefix: str = strings[0]
    for s in strings[1:]:
        # Shorten prefix until it matches the start of s
        while not s.startswith(prefix):
            prefix = prefix[:-1]
    return prefix




def completer(text: str, state: int) -> str | None:
    """Readline completer — completes commands on first token, files on arguments."""
    # Check how much of the line has been typed before the current token
    line_buffer: str = readline.get_line_buffer()
    begin: int = readline.get_begidx()

    # If we are completing the first token, complete command names
    if begin == 0:
        if state == 0:
            completer.matches = sorted(c for c in ALL_COMPLETIONS if c.startswith(text))

        matches: list[str] = completer.matches

        # No matches — ring the bell
        if not matches:
            if state == 0:
                sys.stdout.write(chr(7))
            return None

        # Single match — complete fully with trailing space
        if len(matches) == 1:
            return matches[0] + " " if state == 0 else None

        # Multiple matches — find longest common prefix
        lcp: str = longest_common_prefix(matches)

        if lcp != text:
            # Complete to LCP silently
            return lcp if state == 0 else None
        else:
            # Already at LCP — print matches and redisplay
            if state == 0:
                sys.stdout.write(chr(10) + "  ".join(matches) + chr(10))
                readline.redisplay()
            return None

    # Otherwise complete file/directory names using glob
    if state == 0:
        import glob
        # Match files starting with text, append / to directories
        raw: list[str] = glob.glob(text + "*")
        completer.matches = [
            (m + "/" if os.path.isdir(m) else m) for m in sorted(raw)
        ]

    matches = completer.matches

    # No file matches — ring the bell
    if not matches:
        if state == 0:
            sys.stdout.write(chr(7))
        return None

    # Single match — return it directly
    if len(matches) == 1:
        return matches[0] if state == 0 else None

    # Multiple matches — complete to longest common prefix first
    lcp: str = longest_common_prefix(matches)

    if lcp != text:
        # Can complete further — return LCP silently
        return lcp if state == 0 else None
    else:
        # Already at LCP — show all matches
        if state == 0:
            sys.stdout.write(chr(10) + "  ".join(matches) + chr(10))
            readline.redisplay()
        return None


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


def run_single(parts: list[str], stdin=None, stdout=None, stderr=None):
    """Run a single parsed command with given stdio handles.
    Returns a subprocess.Popen for external commands, or None for builtins."""
    # Extract any redirections, leaving only the command and its args
    parts, stdout_file, stdout_mode, stderr_file, stderr_mode = parse_redirects(parts)

    # Open redirection files if specified, otherwise use the pipe handles passed in
    out = open(stdout_file, stdout_mode) if stdout_file else stdout
    err = open(stderr_file, stderr_mode) if stderr_file else stderr

    try:
        if not parts:
            return None

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

        elif cmd == "history":
            total: int = readline.get_current_history_length()

            # If a number is given, show only the last N entries
            if args:
                limit: int = int(args[0])
                start: int = max(1, total - limit + 1)
            else:
                # No argument — show all entries
                start = 1

            for idx in range(start, total + 1):
                print(f"  {idx}  {readline.get_history_item(idx)}", file=out or sys.stdout)

        elif cmd == "cd":
            # Require exactly one argument
            if not args:
                print("cd: missing argument", file=err or sys.stderr)
                return None

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
                # Return the Popen object so the caller can chain pipes
                return subprocess.Popen(
                    [external_path] + args,
                    stdin=stdin,
                    stdout=out or subprocess.PIPE if stdout == subprocess.PIPE else out,
                    stderr=err if err else None,
                )
            else:
                # Unknown command is an error, so it goes to stderr
                print(f"{cmd}: command not found", file=err or sys.stderr)

    finally:
        # Only close files we opened ourselves, not passed-in pipe handles
        if stdout_file and out:
            out.close()
        if stderr_file and err:
            err.close()

    return None


def handle_pipeline(segments: list[list[str]]) -> None:
    """Execute a list of command segments connected by pipes.
    Handles both external commands and builtins as pipeline stages."""
    processes: list[subprocess.Popen] = []
    prev_read_fd = None   # read end of previous pipe, passed as stdin to next segment

    for i, parts in enumerate(segments):
        is_last: bool = (i == len(segments) - 1)

        if is_last:
            # Last segment writes directly to terminal stdout
            proc = run_single(
                parts,
                stdin=os.fdopen(prev_read_fd, "r") if prev_read_fd is not None else None,
                stdout=None,
            )
            if proc:
                proc.wait()
        else:
            # Create a pipe: write end goes to this segment, read end goes to next
            read_fd, write_fd = os.pipe()
            write_file = os.fdopen(write_fd, "w")

            proc = run_single(
                parts,
                stdin=os.fdopen(prev_read_fd, "r") if prev_read_fd is not None else None,
                stdout=write_file,
            )

            # Close the write end in the parent — the child (or builtin) owns it
            write_file.close()

            if proc:
                # External command — it writes to write_fd via Popen
                processes.append(proc)

            # Pass the read end to the next segment
            prev_read_fd = read_fd

    # Wait for all external processes to finish
    for proc in processes:
        proc.wait()


def handle_command(command: str) -> None:
    """Parse and execute a shell command, handling pipes if present."""
    # shlex.split() handles quoting and backslash escaping
    parts: list[str] = shlex.split(command, posix=True)

    # Ignore empty input (user just pressed Enter)
    if not parts:
        return

    # Split on pipe tokens to get individual command segments
    segments: list[list[str]] = []
    current: list[str] = []
    for token in parts:
        if token == "|":
            segments.append(current)
            current = []
        else:
            current.append(token)
    segments.append(current)

    if len(segments) > 1:
        # Pipeline — hand off to handle_pipeline
        handle_pipeline(segments)
    else:
        # Single command — run directly
        run_single(parts)


def find_in_path(cmd: str) -> str | None:
    """Search PATH directories for an executable named cmd.
    Returns the full path if found, otherwise None."""
    path_dirs: list[str] = os.environ.get("PATH", "").split(os.pathsep)

    for directory in path_dirs:
        full_path: str = os.path.join(directory, cmd)
        if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
            return full_path

    return None


# Path to the history file in the user's home directory
HISTORY_FILE: str = os.path.join(os.path.expanduser("~"), ".shell_history")


def main() -> None:
    """Main REPL loop — print prompt, read input, handle command."""
    # Build the completion cache once at startup
    build_completions()

    # Register the completer and set tab as the completion key
    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")
    # Ensure / and ~ are not treated as delimiters so full paths are passed to completer
    readline.set_completer_delims(" \t\n")

    # Load history from file if it exists
    if os.path.exists(HISTORY_FILE):
        readline.read_history_file(HISTORY_FILE)

    while True:
        # Pass prompt to input() so readline knows the cursor offset
        command: str = input("$ ")

        handle_command(command)


if __name__ == "__main__":
    main()