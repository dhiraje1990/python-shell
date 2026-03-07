import os, shlex, subprocess

BUILTINS = {"exit", "pwd", "echo", "cd"}

def run(line):
    parts = shlex.split(line)
    cmd, args = parts[0], parts[1:]
    if not run_builtin(cmd, args):
        run_external(cmd, args)

def run_builtin(cmd, args):
    if cmd == "exit":
        raise SystemExit(0)
    elif cmd == "pwd":
        print(os.getcwd())
    elif cmd == "echo":
        print(" ".join(args))
    elif cmd == "cd":
        path = args[0] if args else os.path.expanduser("~")
        try:
            os.chdir(path)
        except FileNotFoundError:
            print(f"cd: {path}: No such file or directory")
    else:
        return False
    return True

def run_external(cmd, args):
    try:
        subprocess.run([cmd] + args)
    except FileNotFoundError:
        print(f"myshell: {cmd}: command not found")

def main():
    while True:
        try:
            line = input("myshell> ").strip()
            if not line:
                continue
            run(line)
        except KeyboardInterrupt:
            print()
        except EOFError:
            print("exit")
            break

if __name__ == "__main__":
    main()
