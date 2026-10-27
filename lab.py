import argparse
import datetime
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import threading

PROJECT = Path(__file__).resolve().parent
WORK = PROJECT.parents[2] / "scratch" / "xnu-lab"
SOURCE = WORK / "source"
REVISION = "f6217f891ac0bb64f3d375211650a4c1ff8ca1ea"
TAG = "xnu-12377.1.9"
VERSION = TAG.removeprefix("xnu-")
REPOSITORY = "https://github.com/apple-oss-distributions/xnu"


def run(command, cwd=PROJECT, timeout=60):
    return subprocess.run(command, cwd=cwd, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=timeout, check=False)


def verify_source(source=SOURCE):
    result = run(["git", "rev-parse", "HEAD"], cwd=source)
    if result.returncode or result.stdout.strip() != REVISION:
        raise RuntimeError("Source revision differs from the pinned revision")
    result = run(["git", "status", "--porcelain", "--untracked-files=all"],
                 cwd=source)
    if result.returncode or result.stdout.strip():
        raise RuntimeError("Upstream source must be clean, including untracked files")


def make_command(sdk="macosx", kdk=None, target="all"):
    command = ["/usr/bin/make", "-j2", "MAKEJOBS=-j2", f"SDKROOT={sdk}",
               "ARCH_CONFIGS=ARM64", "KERNEL_CONFIGS=DEVELOPMENT",
               "MACHINE_CONFIGS=VMAPPLE", f"RC_DARWIN_KERNEL_VERSION={VERSION}"]
    for name in ("obj", "sym", "dst"):
        command.append(f"{name.upper()}ROOT={WORK / 'build' / name}")
    if kdk:
        command.append(f"KDKROOT={Path(kdk).resolve()}")
    command.append(f"MAKE_SYMBOL_ALIASING={PROJECT / 'symbol-aliasing.sh'}")
    command.append(target)
    return command


def logged(command, cwd, seconds, label):
    logs = PROJECT / "logs"
    logs.mkdir(exist_ok=True)
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = logs / f"{stamp}-{label}.log"
    print(f"log: {path}", flush=True)
    with path.open("w") as output:
        header = f"revision={REVISION}\ncwd={cwd}\ncommand={shlex.join(command)}\n"
        output.write(header)
        output.flush()
        print(header, end="", flush=True)
        process = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True,
                                   start_new_session=True)
        expired = threading.Event()

        def stop():
            expired.set()
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass

        def kill():
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

        timer = threading.Timer(seconds, stop)
        killer = threading.Timer(seconds + 5, kill)
        timer.start()
        killer.start()
        try:
            for line in process.stdout:
                output.write(line)
                output.flush()
                print(line, end="", flush=True)
            status = process.wait()
        except BaseException:
            kill()
            process.wait()
            raise
        finally:
            timer.cancel()
            killer.cancel()
            process.stdout.close()
        if expired.is_set():
            status = 124
        footer = f"exit_status={status} timeout={int(expired.is_set())}\n"
        output.write(footer)
        print(footer, end="", flush=True)
        return status if status >= 0 else 1


def preflight(sdk):
    commands = [["uname", "-a"], ["sw_vers"], ["xcodebuild", "-version"],
                ["xcrun", "--sdk", sdk, "--show-sdk-path"],
                ["xcrun", "--sdk", sdk, "--show-sdk-version"]]
    for tool in ("clang", "clang++", "mig", "migcom", "iig", "dsymutil",
                 "ctfconvert", "ctfmerge", "flex", "bison", "gm4"):
        commands.append(["xcrun", "--sdk", sdk, "--find", tool])
    failures = 0
    for command in commands:
        result = run(command)
        print(f"$ {shlex.join(command)}\n{result.stdout}status={result.returncode}",
              flush=True)
        failures += result.returncode != 0
    print(f"tool_probe_failures={failures}; optional tools may be absent")
    verify_source()
    print(f"source_verified={REVISION} target=ARM64/VMAPPLE/DEVELOPMENT")
    print("Host kernel, VM guest, and source versions are NOT assumed compatible.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("fetch", "preflight", "probe", "build"))
    parser.add_argument("--sdk", default="macosx")
    parser.add_argument("--kdk")
    parser.add_argument("--seconds", type=int, default=120)
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= 86400:
        parser.error("--seconds must be between 1 and 86400")
    if args.action == "fetch":
        if not SOURCE.exists():
            WORK.mkdir(parents=True, exist_ok=True)
            status = logged(["git", "clone", "--depth", "1", "--branch", TAG,
                             REPOSITORY, str(SOURCE)], WORK, args.seconds, "fetch")
            if status:
                return status
        verify_source()
        dependency = WORK / "availability"
        if not dependency.exists():
            status = logged(["git", "clone", "--depth", "1", "--branch",
                             "AvailabilityVersions-157.2",
                             "https://github.com/apple-oss-distributions/AvailabilityVersions",
                             str(dependency)], WORK, args.seconds, "fetch-availability")
            if status:
                return status
        revision = run(["git", "rev-parse", "HEAD"], cwd=dependency)
        if revision.returncode or revision.stdout.strip() != (
                "149b1777f3e8c2133042d8e188f72e3adf6a7110"):
            raise RuntimeError("AvailabilityVersions revision mismatch")
        return 0
    verify_source()
    if args.action == "preflight":
        return logged([sys.executable, "-u", str(Path(__file__).resolve()),
                       "preflight-child", args.sdk], PROJECT, args.seconds,
                      "preflight")
    for name in ("obj", "sym", "dst"):
        (WORK / "build" / name).mkdir(parents=True, exist_ok=True)
    command = make_command(args.sdk, args.kdk)
    if args.action == "probe":
        command.insert(1, "-n")
    status = logged(command, SOURCE, args.seconds, args.action)
    verify_source()
    return status


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "preflight-child":
            sys.exit(preflight(sys.argv[2]))
        sys.exit(main())
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(f"xnu-lab: {error}", file=sys.stderr)
        sys.exit(1)
