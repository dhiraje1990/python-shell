import sys
import os
import subprocess
import shlex
import readline
import glob
from typing import Optional

HISTORY_FILE: str = os.path.join(os.path.expanduser("~"), ".shell_history")


class Completer:
    """Handles tab-completion for commands and file paths via readline."""

    BUILTINS: set[str] = {"exit", "echo", "type", "pwd", "cd", "history"}

    def __init__(self):
        self._all_completions: set[str] = set()  # Union of builtins + PATH executables
        self._matches: list[str] = []            # Candidates for the current Tab press
        self._build_completions()

    # ------------------------------------------------------------------ #
    #  Setup                                                               #
    # ------------------------------------------------------------------ #

    def _get_path_executables(self) -> set[str]:
        """Walk every directory in PATH and collect executable filenames."""
        executables: set[str] = set()
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            try:
                for name in os.listdir(directory):
                    full_path = os.path.join(directory, name)
                    if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                        executables.add(name)
            except PermissionError:
                pass  # Skip directories we cannot read
        return executables

    def _build_completions(self) -> None:
        """Populate the completion cache with builtins and PATH executables."""
        self._all_completions = self.BUILTINS | self._get_path_executables()

    def register(self) -> None:
        """Bind this completer to readline and configure delimiter settings."""
        readline.set_completer(self.complete)
        readline.parse_and_bind("tab: complete")
        # Keep / and ~ out of delimiters so full paths reach the completer intact
        readline.set_completer_delims(" \t\n")

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _longest_common_prefix(strings: list[str]) -> str:
        """Return the longest string that is a prefix of every item in the list."""
        if not strings:
            return ""
        prefix = strings[0]
        for s in strings[1:]:
            while not s.startswith(prefix):
                prefix = prefix[:-1]
        return prefix

    def _show_matches(self, matches: list[str], current_text: str) -> None:
        """Print all matches on a new line, then redraw the prompt and current input."""
        sys.stdout.write("\n" + "  ".join(matches) + "\n")
        sys.stdout.flush()
        # Manually reprint prompt + buffer so readline redraws in the right position
        sys.stdout.write("$ " + readline.get_line_buffer())
        sys.stdout.flush()
        readline.redisplay()

    # ------------------------------------------------------------------ #
    #  Readline entry point                                                #
    # ------------------------------------------------------------------ #

    def complete(self, text: str, state: int) -> Optional[str]:
        """Readline calls this repeatedly with state=0,1,2,… to iterate matches.
        Delegates to command or path completion based on cursor position."""
        begin: int = readline.get_begidx()

        # Completing the first token → match command names
        if begin == 0:
            return self._complete_command(text, state)

        # Completing a later token → match file/directory names
        return self._complete_path(text, state)

    # ------------------------------------------------------------------ #
    #  Command completion                                                  #
    # ------------------------------------------------------------------ #

    def _complete_command(self, text: str, state: int) -> Optional[str]:
        """Complete the command name against builtins and PATH executables."""
        if state == 0:
            # Build match list once per Tab press (state resets to 0 each time)
            self._matches = sorted(c for c in self._all_completions if c.startswith(text))

        matches = self._matches

        if not matches:
            if state == 0:
                sys.stdout.write(chr(7))  # Bell — no match found
            return None

        if len(matches) == 1:
            # Unique match — append a space so the user can type args immediately
            return matches[0] + " " if state == 0 else None

        lcp = self._longest_common_prefix(matches)

        if lcp != text:
            # Can narrow down further — silently complete to the common prefix
            return lcp if state == 0 else None

        # Already at the longest common prefix — show all options
        if state == 0:
            self._show_matches(matches, text)
        return None

    # ------------------------------------------------------------------ #
    #  Path completion                                                     #
    # ------------------------------------------------------------------ #

    def _complete_path(self, text: str, state: int) -> Optional[str]:
        """Complete a file or directory name using glob expansion."""
        if state == 0:
            raw = glob.glob(text + "*")
            # Append / to directories so the user knows they can descend further
            self._matches = [
                (m + "/" if os.path.isdir(m) else m) for m in sorted(raw)
            ]

        matches = self._matches

        if not matches:
            if state == 0:
                sys.stdout.write(chr(7))  # Bell — no file match
            return None

        if len(matches) == 1:
            return matches[0] if state == 0 else None

        lcp = self._longest_common_prefix(matches)

        if lcp != text:
            # Partial disambiguation available — complete silently to the LCP
            return lcp if state == 0 else None

        # Already at LCP — list all matching paths
        if state == 0:
            self._show_matches(matches, text)
        return None


class RedirectParser:
    """Parses shell redirection tokens (>, >>, 2>, 2>>) out of a token list."""

    @staticmethod
    def parse(parts: list[str]) -> tuple[list[str], Optional[str], str, Optional[str], str]:
        """Strip redirection tokens from *parts* and return metadata.

        Returns:
            clean_args  — token list with all redirection operators removed
            stdout_file — path to redirect stdout to, or None
            stdout_mode — 'w' (overwrite) or 'a' (append)
            stderr_file — path to redirect stderr to, or None
            stderr_mode — 'w' (overwrite) or 'a' (append)
        """
        clean: list[str] = []
        stdout_file: Optional[str] = None
        stdout_mode: str = "w"
        stderr_file: Optional[str] = None
        stderr_mode: str = "w"

        i = 0
        while i < len(parts):
            if parts[i] == ">>" and i + 1 < len(parts):
                stdout_file, stdout_mode = parts[i + 1], "a"
                i += 2
            elif parts[i] in (">", "1>") and i + 1 < len(parts):
                stdout_file, stdout_mode = parts[i + 1], "w"
                i += 2
            elif parts[i] == "2>>" and i + 1 < len(parts):
                stderr_file, stderr_mode = parts[i + 1], "a"
                i += 2
            elif parts[i] == "2>" and i + 1 < len(parts):
                stderr_file, stderr_mode = parts[i + 1], "w"
                i += 2
            else:
                clean.append(parts[i])
                i += 1

        return clean, stdout_file, stdout_mode, stderr_file, stderr_mode


class Shell:
    """The main shell: REPL loop, command dispatch, builtins, and pipeline execution."""

    BUILTINS: set[str] = {"exit", "echo", "type", "pwd", "cd", "history"}

    def __init__(self):
        self._completer = Completer()
        self._redirect_parser = RedirectParser()
        self._history_offset: int = 0  # Tracks entries loaded at startup for append-only saves

    # ------------------------------------------------------------------ #
    #  Startup                                                             #
    # ------------------------------------------------------------------ #

    def setup_readline(self) -> None:
        """Configure readline: register completer and load history from disk."""
        self._completer.register()
        if os.path.exists(HISTORY_FILE):
            readline.read_history_file(HISTORY_FILE)
        self._history_offset = readline.get_current_history_length()

    def run(self) -> None:
        """Start the REPL — print prompt, read input, execute, repeat."""
        self.setup_readline()
        while True:
            try:
                command = input("$ ")
            except EOFError:
                # Ctrl+D — exit cleanly
                sys.exit(0)

            self.handle_command(command)
            self._save_history()

    # ------------------------------------------------------------------ #
    #  History                                                             #
    # ------------------------------------------------------------------ #

    def _save_history(self) -> None:
        """Append only the commands added this session, preserving earlier entries."""
        new_entries = readline.get_current_history_length() - self._history_offset
        readline.append_history_file(new_entries, HISTORY_FILE)
        self._history_offset = readline.get_current_history_length()

    # ------------------------------------------------------------------ #
    #  Command parsing                                                     #
    # ------------------------------------------------------------------ #

    def handle_command(self, command: str) -> None:
        """Tokenise the raw input, split on pipes, and dispatch for execution."""
        parts = shlex.split(command, posix=True)
        if not parts:
            return  # User pressed Enter on an empty line

        # Gather pipe-separated segments into a list of token lists
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
            self._handle_pipeline(segments)
        else:
            self._run_single(parts)

    # ------------------------------------------------------------------ #
    #  Path search                                                         #
    # ------------------------------------------------------------------ #

    def _find_in_path(self, cmd: str) -> Optional[str]:
        """Search PATH for an executable named *cmd*; return its full path or None."""
        for directory in os.environ.get("PATH", "").split(os.pathsep):
            full_path = os.path.join(directory, cmd)
            if os.path.isfile(full_path) and os.access(full_path, os.X_OK):
                return full_path
        return None

    # ------------------------------------------------------------------ #
    #  Single-command execution                                            #
    # ------------------------------------------------------------------ #

    def _run_single(self, parts: list[str], stdin=None, stdout=None, stderr=None):
        """Execute one command (builtin or external) with optional stdio overrides.

        Handles redirection internally; returns a Popen for external commands so
        the pipeline runner can chain them, or None for builtins.
        """
        # Pull redirection metadata out before looking at the command name
        parts, stdout_file, stdout_mode, stderr_file, stderr_mode = \
            self._redirect_parser.parse(parts)

        # Open redirect targets; fall back to the pipe handles passed by the caller
        out = open(stdout_file, stdout_mode) if stdout_file else stdout
        err = open(stderr_file, stderr_mode) if stderr_file else stderr

        try:
            if not parts:
                return None

            cmd, args = parts[0], parts[1:]

            if cmd == "exit":
                sys.exit(int(args[0]) if args else 0)

            elif cmd == "echo":
                print(" ".join(args), file=out or sys.stdout)

            elif cmd == "type":
                # Report whether each argument is a builtin or an external executable
                for arg in args:
                    if arg in self.BUILTINS:
                        print(f"{arg} is a shell builtin", file=out or sys.stdout)
                    else:
                        path = self._find_in_path(arg)
                        if path:
                            print(f"{arg} is {path}", file=out or sys.stdout)
                        else:
                            print(f"{arg}: not found", file=err or sys.stderr)

            elif cmd == "pwd":
                print(os.getcwd(), file=out or sys.stdout)

            elif cmd == "history":
                total = readline.get_current_history_length()
                # Optional numeric argument limits output to the last N entries
                start = max(1, total - int(args[0]) + 1) if args else 1
                for idx in range(start, total + 1):
                    print(f"  {idx}  {readline.get_history_item(idx)}", file=out or sys.stdout)

            elif cmd == "cd":
                if not args:
                    print("cd: missing argument", file=err or sys.stderr)
                    return None
                target = os.path.expanduser(args[0])  # Expand ~ to home directory
                try:
                    os.chdir(target)
                except FileNotFoundError:
                    print(f"cd: {target}: No such file or directory", file=err or sys.stderr)
                except NotADirectoryError:
                    print(f"cd: {target}: Not a directory", file=err or sys.stderr)
                except PermissionError:
                    print(f"cd: {target}: Permission denied", file=err or sys.stderr)

            else:
                # Unknown command — try to find and launch it as an external executable
                path = self._find_in_path(cmd)
                if path:
                    return subprocess.Popen(
                        [path] + args,
                        stdin=stdin,
                        stdout=out or subprocess.PIPE if stdout == subprocess.PIPE else out,
                        stderr=err if err else None,
                    )
                else:
                    print(f"{cmd}: command not found", file=err or sys.stderr)

        finally:
            # Close only files we opened here — never close caller-supplied handles
            if stdout_file and out:
                out.close()
            if stderr_file and err:
                err.close()

        return None

    # ------------------------------------------------------------------ #
    #  Pipeline execution                                                  #
    # ------------------------------------------------------------------ #

    def _handle_pipeline(self, segments: list[list[str]]) -> None:
        """Connect a sequence of commands with pipes and run them concurrently."""
        processes: list[subprocess.Popen] = []
        prev_read_fd = None  # Read end of the previous pipe; becomes stdin for the next stage

        for i, parts in enumerate(segments):
            is_last = (i == len(segments) - 1)

            if is_last:
                # Final stage inherits the terminal's stdout directly
                proc = self._run_single(
                    parts,
                    stdin=os.fdopen(prev_read_fd, "r") if prev_read_fd is not None else None,
                    stdout=None,
                )
                if proc:
                    proc.wait()
            else:
                # Intermediate stage: create a pipe and write into it
                read_fd, write_fd = os.pipe()
                write_file = os.fdopen(write_fd, "w")

                proc = self._run_single(
                    parts,
                    stdin=os.fdopen(prev_read_fd, "r") if prev_read_fd is not None else None,
                    stdout=write_file,
                )
                # Close the write end in the parent; the child process owns it now
                write_file.close()

                if proc:
                    processes.append(proc)

                prev_read_fd = read_fd  # Hand the read end to the next stage

        # Reap all child processes once the pipeline is drained
        for proc in processes:
            proc.wait()


if __name__ == "__main__":
    Shell().run()