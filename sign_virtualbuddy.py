from pathlib import Path
import plistlib
import subprocess

PROJECT = Path(__file__).resolve().parent
SHARED = Path("/Volumes/porter-crush/home/shared")
SOURCE = SHARED / "VirtualBuddy-diagnostic-build/Build/Products/Release/VirtualBuddy.app"
DESTINATION = SHARED / "VirtualBuddy-Diagnostic.app"


def command(*arguments):
    subprocess.run(arguments, check=True, timeout=120)


def main():
    if DESTINATION.exists():
        raise RuntimeError("Diagnostic app already exists; refusing overwrite")
    command("ditto", str(SOURCE), str(DESTINATION))
    targets = [path for path in DESTINATION.rglob("*")
               if path.suffix in (".app", ".xpc", ".framework") and not path.is_symlink()]
    targets.sort(key=lambda path: len(path.parts), reverse=True)
    targets.append(DESTINATION)
    for path in targets:
        options = ["codesign", "--force", "--sign", "-", "--timestamp=none", "--options", "0"]
        entitlements = {}
        if path == DESTINATION:
            entitlements = {"com.apple.security.virtualization": True,
                            "com.apple.security.device.audio-input": True}
        elif path.name == "VirtualBuddyGuestHelper.app":
            entitlements = {"com.apple.security.app-sandbox": True}
        if entitlements:
            filename = PROJECT / f"{path.name}.local-entitlements.plist"
            filename.write_bytes(plistlib.dumps(entitlements))
            options.extend(["--entitlements", str(filename)])
        command(*options, str(path))
    command("codesign", "--verify", "--deep", "--strict", "--verbose=2", str(DESTINATION))
    print(f"diagnostic_app={DESTINATION}")


if __name__ == "__main__":
    main()
