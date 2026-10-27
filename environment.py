import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import lab

KITS = {
    "25A353": "b37a43c861f7d22235b0ae8279f040a7731290c25d2d85f5c423a0d1fc96e0b3",
    "25E246": "7bf032f5b7d75b0cf19b077b5408e03b04ada4dd8e7921c9cb4fcdb9c7015630",
}
PROJECTS = ("bootstrap_cmds", "dtrace", "AvailabilityVersions", "Libsystem",
            "libplatform", "libdispatch")


def write_changed(path, content):
    if not path.exists() or path.read_text() != content:
        path.write_text(content)


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def execute(command, label, seconds=120):
    status = lab.logged(command, lab.PROJECT, seconds, label)
    if status:
        raise RuntimeError(f"{label} failed with status {status}")


def extract(build):
    archive = lab.WORK / f"kdk-{build}.dmg"
    if digest(archive) != KITS[build]:
        raise RuntimeError(f"Checksum mismatch for {archive}")
    destination = lab.WORK / f"kdk-{build}"
    packages = destination / "packages"
    packages.mkdir(parents=True, exist_ok=True)
    package = packages / "Kernel Debug Kit" / "KernelDebugKit.pkg"
    if not package.exists():
        execute(["7zz", "x", "-y", "-mmt=2", f"-o{packages}", str(archive),
                 "Kernel Debug Kit/KernelDebugKit.pkg"], f"extract-{build}")
    execute(["pkgutil", "--check-signature", str(package)], f"signature-{build}")
    expanded = destination / "expanded"
    if not expanded.exists():
        execute(["pkgutil", "--expand-full", str(package), str(expanded)],
                f"expand-{build}", 300)
    root = destination / "root"
    root.mkdir(exist_ok=True)
    payloads = sorted(expanded.glob("*.pkg/Payload"))
    if not payloads:
        raise RuntimeError("No KDK package payloads found")
    for payload in payloads:
        execute(["ditto", str(payload), str(root)], f"stage-{build}")
    print(f"extracted_kdk={root}")
    return root


def fetch():
    release = json.loads((lab.WORK / "release-260.json").read_text())
    tags = {item["project"]: item["tag"] for item in release["projects"]}
    sources = lab.WORK / "dependencies"
    sources.mkdir(exist_ok=True)
    locked = {}
    for project in PROJECTS:
        source = sources / project
        if not source.exists():
            execute(["git", "clone", "--depth", "1", "--branch", tags[project],
                     f"https://github.com/apple-oss-distributions/{project}",
                     str(source)], f"fetch-{project}")
        revision = lab.run(["git", "rev-parse", "HEAD"], cwd=source)
        tag = lab.run(["git", "rev-parse", f"{tags[project]}^{{commit}}"], cwd=source)
        dirty = lab.run(["git", "status", "--porcelain", "--untracked-files=all"],
                        cwd=source)
        if revision.returncode or tag.returncode or dirty.returncode or (
                revision.stdout != tag.stdout) or dirty.stdout.strip():
            raise RuntimeError(f"Dependency validation failed: {project}")
        locked[project] = {"tag": tags[project], "commit": revision.stdout.strip()}
    lock = lab.PROJECT / "dependencies.lock.json"
    if lock.exists() and json.loads(lock.read_text()) != locked:
        raise RuntimeError("Dependency lock changed; refusing replacement")
    lock.write_text(json.dumps(locked, indent=2) + "\n")
    security = lab.WORK / "security"
    if not security.exists():
        execute(["git", "clone", "--depth", "1", "--branch", "Security-55471.14.18",
                 "--filter=blob:none", "--sparse",
                 "https://github.com/apple-oss-distributions/Security", str(security)],
                "fetch-security")
    result = lab.run(["git", "rev-parse", "Security-55471.14.18^{commit}"], cwd=security)
    if result.returncode:
        execute(["git", "-C", str(security), "fetch", "--depth", "1", "origin",
                 "tag", "Security-55471.14.18"], "fetch-security-tag")
        result = lab.run(["git", "rev-parse", "Security-55471.14.18^{commit}"], cwd=security)
    if result.returncode or result.stdout.strip() != "5437914d400816e369940421d1417d37822a8fbe":
        raise RuntimeError("Security DER source revision mismatch")


def merge_tree(source, destination):
    destination.mkdir(parents=True, exist_ok=True)
    for item in source.iterdir():
        target = destination / item.name
        if item.is_dir() and not item.is_symlink():
            if target.is_symlink():
                previous = target.resolve()
                target.unlink()
                merge_tree(previous, target)
            merge_tree(item, target)
        elif not target.exists() and not target.is_symlink():
            target.symlink_to(item.resolve())


def prepare():
    sdk_result = lab.run(["xcrun", "--sdk", "macosx", "--show-sdk-path"])
    if sdk_result.returncode:
        raise RuntimeError(sdk_result.stdout)
    sdk = lab.WORK / "MacOSX26.2.sdk"
    merge_tree(Path(sdk_result.stdout.strip()), sdk)
    merge_tree(lab.WORK / "kdk-25A353" / "root", sdk)
    availability = lab.WORK / "dependencies" / "AvailabilityVersions"
    tools = sdk / "usr/local/libexec"
    tools.mkdir(parents=True, exist_ok=True)
    for name in ("availability", "availability.pl", "availability.dsl"):
        target = tools / name
        if not target.exists():
            target.symlink_to(availability / name)
    platform = lab.WORK / "dependencies" / "libplatform"
    merge_tree(platform / "include", sdk / "usr/local/include")
    merge_tree(platform / "private", sdk / "usr/local/include")
    print(f"sdk_overlay={sdk}")


def headers():
    command = lab.make_command(str(lab.WORK / "MacOSX26.2.sdk"),
                               lab.WORK / "kdk-25A353/root", "installhdrs")
    command = [entry for entry in command if not entry.startswith(
        ("OBJROOT=", "SYMROOT=", "DSTROOT=", "MAKE_SYMBOL_ALIASING="))]
    sdk_version = lab.run(["xcrun", "--sdk", "macosx", "--show-sdk-version"])
    platform = lab.run(["xcrun", "--sdk", "macosx", "--show-sdk-platform-path"])
    if sdk_version.returncode or platform.returncode:
        raise RuntimeError("Cannot resolve base SDK metadata")
    command.extend([f"SDKVERSION={sdk_version.stdout.strip()}",
                    f"PLATFORMPATH={platform.stdout.strip()}", "PLATFORM=MacOSX",
                    f"OBJROOT={lab.WORK / 'headers/obj'}",
                    f"SYMROOT={lab.WORK / 'headers/sym'}",
                    f"DSTROOT={lab.WORK / 'headers/root'}"])
    status = lab.logged(command, lab.SOURCE, 120, "kernel-headers")
    lab.verify_source()
    if status:
        raise RuntimeError(f"Kernel headers failed with status {status}")
    merge_tree(lab.WORK / "headers/root", lab.WORK / "MacOSX26.2.sdk")


def firehose():
    sdk = lab.WORK / "MacOSX26.2.sdk"
    source = lab.WORK / "dependencies/libdispatch"
    output = lab.WORK / "firehose"
    output.mkdir(exist_ok=True)
    command = ["xcrun", "--sdk", "macosx", "clang", "-arch", "arm64e",
               "-isysroot", str(sdk), "-std=gnu11", "-O2", "-mkernel",
               "-nostdinc", "-Wno-packed", "-DKERNEL=1", "-DDISPATCH_USE_DTRACE=0",
               "-DOS_ATOMIC_CONFIG_MEMORY_ORDER_DEPENDENCY=1",
               "-DOS_ATOMIC_CONFIG_STARVATION_FREE_ONLY=0", f"-I{source}"]
    for path in ("System/Library/Frameworks/Kernel.framework/PrivateHeaders",
                 "System/Library/Frameworks/Kernel.framework/Headers",
                 "usr/local/include/os", "usr/local/include/firehose"):
        command.append(f"-I{sdk / path}")
    command.extend(["-c", str(source / "src/firehose/firehose_buffer.c"),
                    "-o", str(output / "firehose.o")])
    execute(command, "firehose-compile")
    library = sdk / "usr/local/lib/kernel/libfirehose_kernel.a"
    library.parent.mkdir(parents=True, exist_ok=True)
    execute(["xcrun", "libtool", "-static", "-o", str(library),
             str(output / "firehose.o")], "firehose-archive")
    header = lab.run(["xcrun", "unifdef", "-DKERNEL=1", "-DOS_FIREHOSE_SPI=1",
                      "-DOS_VOUCHER_ACTIVITY_SPI_TYPES=1", "-UOS_VOUCHER_ACTIVITY_SPI",
                      str(source / "os/firehose_buffer_private.h")])
    if header.returncode not in (0, 1):
        raise RuntimeError(header.stdout)
    destination = sdk / "usr/local/include/kernel/os/firehose_buffer_private.h"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(header.stdout)


def build_kernel():
    sdk = lab.WORK / "MacOSX26.2.sdk"
    kdk = lab.WORK / "kdk-25A353/root"
    additions = lab.WORK / "additions"
    additions.mkdir(exist_ok=True)
    ce = lab.WORK / "kdk-25E246/root/System/Library/Frameworks/Kernel.framework/Versions/A/PrivateHeaders/platform/CoreEntitlements"
    for header in ce.rglob("*.h"):
        destination = additions / "CoreEntitlements" / header.relative_to(ce)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink():
            destination.unlink()
        destination.symlink_to(header)
    kernel_header = additions / "CoreEntitlements/V2/Kernel.h"
    if not kernel_header.exists():
        kernel_header.symlink_to(lab.WORK / "kdk-25E246/root/System/Library/KernelSupport/CoreEntitlements/V2/Kernel.h")
    security = lab.WORK / "security"
    names = lab.run(["git", "ls-tree", "-r", "--name-only",
                     "Security-55471.14.18", "libsecurity_keychain/libDER/libDER"],
                    cwd=security)
    if names.returncode:
        raise RuntimeError(names.stdout)
    for name in names.stdout.splitlines():
        if not name.endswith(".h"):
            continue
        content = lab.run(["git", "show", f"Security-55471.14.18:{name}"],
                          cwd=security)
        if content.returncode:
            raise RuntimeError(content.stdout)
        destination = additions / "libDER" / Path(name).name
        destination.parent.mkdir(exist_ok=True)
        write_changed(destination, content.stdout)
    iboot = additions / "iBoot/boot_args_abi.h"
    iboot.parent.mkdir(exist_ok=True)
    write_changed(iboot, "#define IBOOT_MAX_ENV_VAR_DATA_SIZE 4096\n")
    original = lab.SOURCE / "osfmk/vm/vm_resident.c"
    text = original.read_text()
    include = "#include <AppleFeatures.h>\n"
    if text.count(include) != 1:
        raise RuntimeError("Unexpected AppleFeatures include layout")
    derived = additions / "vm_resident.c"
    write_changed(derived, text.replace(include, ""))
    overlay = additions / "clang-overlay.json"
    write_changed(overlay, json.dumps({"version": 0, "roots": [
        {"type": "file", "name": str(original), "external-contents": str(derived)}
    ]}))
    command = lab.make_command(str(sdk), kdk)
    metadata = [("SDKVERSION", "--show-sdk-version"),
                ("PLATFORMPATH", "--show-sdk-platform-path")]
    for key, option in metadata:
        result = lab.run(["xcrun", "--sdk", "macosx", option])
        if result.returncode:
            raise RuntimeError(result.stdout)
        command.append(f"{key}={result.stdout.strip()}")
    private = "System/Library/Frameworks/Kernel.framework/Versions/A/PrivateHeaders"
    command.extend(["PLATFORM=MacOSX",
                    f"INCFLAGS_EXTERN=-I{additions} -I{lab.SOURCE / 'EXTERNAL_HEADERS'}",
                    f"INCFLAGS_SDK=-I{sdk / 'usr/local/include'} -I{kdk / private}",
                    f"INCFLAGS_PLATFORM=-I{kdk / private / 'platform'}",
                    f"KCC=sh {lab.PROJECT / 'kernel-cc.sh'} clang -ivfsoverlay {overlay}",
                    f"CXX=sh {lab.PROJECT / 'kernel-cc.sh'} clang++ -ivfsoverlay {overlay}",
                    f"LDFLAGS_KERNEL_ONLY_CONFIG_DEVELOPMENTARM64=-rdynamic -Wl,-force_load,{kdk / 'System/Library/KernelSupport/libVMAPPLE.os.DEVELOPMENT.a'}"])
    status = lab.logged(command, lab.SOURCE, 120, "kernel-overlay-build")
    lab.verify_source()
    if status:
        raise RuntimeError(f"Kernel build status {status}")


def ctf_tools():
    source = lab.WORK / "dependencies/dtrace"
    root = lab.WORK / "tools"
    command = ["xcodebuild", "-project", str(source / "dtrace.xcodeproj"),
               "-target", "ctfconvert", "-target", "ctfmerge", "-target", "ctfdump",
               "-configuration", "Release", "-sdk", "macosx", "-jobs", "2",
               "install", "SDKROOT=macosx", "ARCHS=arm64", "VALID_ARCHS=arm64",
               "RC_ProjectName=dtrace_ctf", "TOOLCHAIN_INSTALL_DIR=",
               "CODE_SIGNING_ALLOWED=NO", f"DSTROOT={root}",
               f"OBJROOT={lab.WORK / 'ctf/obj'}", f"SYMROOT={lab.WORK / 'ctf/sym'}"]
    execute(command, "ctf-tools-build")


def collection():
    kdk = lab.WORK / "KDK_26.0_25A353.kdk"
    if not kdk.exists():
        kdk.symlink_to(lab.WORK / "kdk-25A353/root", target_is_directory=True)
    kernel = lab.WORK / "build/obj/DEVELOPMENT_ARM64_VMAPPLE/kernel.development.vmapple"
    destination = lab.WORK / "artifacts"
    destination.mkdir(exist_ok=True)
    command = ["/usr/bin/kmutil", "create", "-v", "-V", "development",
               "-a", "arm64e", "-n", "boot", "-s", "none", "--kdk", str(kdk),
               "--sdk", str(lab.WORK / "MacOSX26.2.sdk"),
               "--volume-root", str(kdk), "--repository", str(kdk / "System/Library/Extensions"),
               "--build", "25A353", "--allow-missing-kdk", "-B", str(destination / "xnu-12377.1.9.kc"),
               "-k", str(kernel), "-x"]
    for name in ("System", "AppleVirtualPlatform", "AppleARMGIC",
                 "AppleARMPL011Driver", "AppleVirtIO", "AppleVirtIOStorage",
                 "apfs", "AppleFileSystemDriver", "corecrypto", "pthread", "Sandbox"):
        command.extend(["-p", str(kdk / "System/Library/Extensions" / f"{name}.kext")])
    execute(command, "kernel-collection")


def vm_frontend():
    archive = lab.WORK / "VirtualBuddy_v2.2.1-430.dmg"
    destination = lab.WORK / "virtualbuddy"
    destination.mkdir(exist_ok=True)
    execute(["7zz", "x", "-y", "-mmt=2", f"-o{destination}", str(archive)],
            "extract-virtualbuddy")
    applications = list(destination.glob("**/VirtualBuddy.app"))
    if len(applications) != 1:
        raise RuntimeError(f"Expected one VirtualBuddy application: {applications}")
    execute(["codesign", "--verify", "--deep", "--strict", "--verbose=2",
             str(applications[0])], "verify-virtualbuddy")
    print(f"vm_frontend={applications[0]}")


def verify_kernel():
    root = lab.WORK / "build/obj/DEVELOPMENT_ARM64_VMAPPLE"
    kernel = root / "kernel.development.vmapple"
    symbols = root / "kernel.development.vmapple.dSYM"
    execute(["file", str(kernel)], "verify-kernel-format")
    result = lab.run(["xcrun", "dwarfdump", "--uuid", str(kernel), str(symbols)])
    lines = result.stdout.splitlines()
    if result.returncode or len(lines) != 2 or lines[0].split()[1] != lines[1].split()[1]:
        raise RuntimeError("Kernel and debug-symbol UUIDs do not match")
    print(result.stdout)
    execute(["xcrun", "lldb", "--batch", "-o", f"target create {kernel}",
             "-o", "image lookup -n fmod_watch", "-o", "image lookup -n add_fsevent"],
            "verify-kernel-debugger")
    provenance = {"source": lab.REVISION, "sha256": digest(kernel),
                  "uuid": lines[0].split()[1], "boot_verified": False,
                  "platform_kdk": "25A353", "entitlement_headers_kdk": "25E246",
                  "ctf_embedded": False}
    (lab.PROJECT / "kernel-artifact.json").write_text(json.dumps(provenance, indent=2) + "\n")
    lab.verify_source()


def inventory():
    for build in KITS:
        root = extract(build)
        for relative in (
            "System/Library/KernelSupport/libVMAPPLE.os.DEVELOPMENT.a",
            "System/Library/KernelSupport/CoreEntitlements/V2/Kernel.h",
            "System/Library/Frameworks/Kernel.framework/Versions/A/PrivateHeaders/platform",
        ):
            candidate = root / relative
            print(f"present={int(candidate.exists())} path={candidate}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("fetch", "extract", "inventory", "prepare", "headers", "firehose", "kernel", "ctf", "collection", "vm", "verify"))
    args = parser.parse_args()
    if args.action == "fetch":
        fetch()
    elif args.action == "extract":
        for build in KITS:
            extract(build)
    elif args.action == "prepare":
        prepare()
    elif args.action == "headers":
        headers()
    elif args.action == "firehose":
        firehose()
    elif args.action == "kernel":
        build_kernel()
    elif args.action == "ctf":
        ctf_tools()
    elif args.action == "collection":
        collection()
    elif args.action == "vm":
        vm_frontend()
    elif args.action == "verify":
        verify_kernel()
    else:
        inventory()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print(f"environment: {error}", file=sys.stderr)
        sys.exit(1)
