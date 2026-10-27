# pronghorn

i was running mutation tests on my own build software (`game`). i noticed a
substantial leak in fseventsd (~140mb/hr), which was presumably due to very
lage numbers of deliberately-broken compiles (this is how mutation tests work;
this was not an attempt to fuzz or red-team anything) that interact with the
test suite in game.

when i started building fixtures around fseventsd so i could send a repro and
bug report to apple, the `claude code` harness began to yell at me about it
being both "reasoning extraction" and "cyber." apparently, sending bug reports
is harmful to both anthropic and apple.

as it happens, i'm working on my own harness, and i just sent those same
requests off to other models through other providers. the list of models
includes:

- kimi k3
- gpt 6.1 sol & astra
- fable 5.1
- deepseek v4 pro

turns out nobody was harmed, and this led to my having another 7kloc added to
game, including build chains for c, objc, and swift, and an operational xnu
environment. the problem i ran in to was provenance, and apple just won't let
me run an xnu that i built.

the other thing i accidentally discovered was that beyond a certain point,
testing your own software starts looking a lot like testing other people's
software, and when you're testing other people's software, beyond a certain
degree of completeness begins to look like red-teaming. in fact, it's mostly
indistinguishable from red-teaming.

so, when all this became clear to me, i just added hardening checks to game,
which checks software that it manages ("game-managed projects," including xnu
or anything else). this means that a "hardening" lint pass suddenly includes
checks which *do not pass hardening checks,* which ... well, let's be honest,
*reveals weaknesses in anyone else's code.* this was never really my intent.

one thing to be very clear about this: the `claude` safety classifier works on
language. so if you find yourself getting stuck repeatedly behind this
classifier, the only reasonable response is to move the behavior it is
objecting to away from the language layer and into the binary. so let's
suppose that a certain behavior like "`game find-sploits claude-binary`"
bothers claude. obviously claude objects to `find-sploits`, and if you just
move that `find-sploits` behavior into something like `hardening-lint`, claude
no longer objects because, and i want to say this very clearly, *the claude
harness safety classifier is absolute dogshit at protecting anything.* in
fact, it's worse than that: it just makes someone move the objectionable
behavior out of its view. it *does not actually prevent anything.*

so i figured i'd upload this as a project i was working on but i am not really
using because red teaming is not mything.

# XNU lab

An isolated, game-driven attempt to build Apple's public XNU for an ARM64
VMAPPLE development target. This project is build orchestration, not a Go
kernel or a replacement for Apple's build system. XNU remains C, C++, and
assembly; the small runner is Python with a shell dependency adapter.

## Virtualization bring-up: restore authorization blocker

A signed Swift Virtualization.framework runner is now built as `xnu-vm` in this
project. It has inspect, install, retry-install, run, and recovery actions,
wired through game. The guest has a two-CPU, 4 GiB RAM configuration, NAT,
keyboard/mouse, graphical console, persisted hardware identity and auxiliary
storage, and a 64 GiB sparse disk. It does not alter host boot policy.

The approved shared location resolves to `/Users/jane/var/shared`, on the larger
Data filesystem. Restore-image loading initially failed through the symlink;
canonicalizing the path fixes it. Apple's framework recognizes the downloaded
IPSW as macOS 26.0 build 25A353 and supports its hardware requirements.

**Installation did not succeed.** Both attempts failed; the diagnostic retry
exposed the underlying error:

```text
VZErrorDomain 10007
com.apple.MobileDevice.MobileRestore 3194
Declined to authorize this DFU file on this device for this user.
```

This is Apple's restore-authorization rejection, consistent with the catalog's
unsigned status for the old RC image. Local compatibility checks do not establish
that Apple's restore service will authorize installation. There is no local fix
established here, and root is not a remedy for that rejection.

The incomplete guest directory is preserved at:

```text
home/shared/xnu-lab-macos-26
```

It has no `installed` marker and the runner refuses to boot it as a completed
guest. New installation refuses to overwrite existing storage. `retry-install-vm`
can retry only an incomplete installation and never a completed one. The retry
performs restoration writes to that incomplete guest disk, not the host disk.

```sh
game run build-vm
game run sign-vm
game run inspect-vm
game run install-vm
game run retry-install-vm
game run start-vm
game run recover-vm
```

Use GAME_HOME and the absolute game executable below. Signing is ad hoc with only
the virtualization entitlement, not a request for signing credentials. The Swift
build treats warnings as errors. Invalid CLI arguments exit 2. Install progress
is emitted every five seconds on the initial install; detailed NSError chains
are printed on failure. Logs are `logs/vm-install.log` and
`logs/vm-retry-install.log`. The graphical runner is built/typechecked but its
actual run/recovery paths remain untested because installation failed.

Completing a runnable environment requires either an existing installed matching
macOS 26.0 guest, or an Apple-authorized restore image. A newer authorized image
would require a separately named guest and reconsidering kernel/KDK compatibility;
the 25A353 kernel must not be claimed compatible with it without verification.
No newer image has been downloaded, no failed guest has been deleted, and no
restore-signing or platform security checks have been bypassed.

## Current result, updated after dependency bring-up

**The development kernel now builds and links successfully through game.**
The sections below this update preserve the first-attempt record and are historical
where they say headers are missing or no kernel exists.

Built kernel:

```text
pronghorn/build/obj/DEVELOPMENT_ARM64_VMAPPLE/kernel.development.vmapple
```

The adjacent `.dSYM` has the same UUID, `DA7FB709-348B-3A7F-890F-7CD737199A89`.
LLDB successfully resolves `fmod_watch` and `add_fsevent` to the XNU event source.
`kernel-artifact.json` records the binary hash, source revision, and limitations.
The source checkout remains clean. Nine orchestration tests pass.

### Newly available development environment

- Six matching Apple public dependencies, pinned in `dependencies.lock.json`.
- KDK 26.0/25A353 and KDK 26.4/25E246, downloaded from the Dortania mirror,
  SHA-256 checked against its manifest, then package-signature verified as Apple
  Software before extraction. No installer, mount, root, or global SDK writes.
- Generated XNU public/private headers and an isolated SDK overlay at
  `scratch/xnu-lab/MacOSX26.2.sdk` under this home.
- Kernel firehose archive compiled from matching public libdispatch source.
- `ctfconvert`, `ctfmerge`, and `ctfdump` built from matching public dtrace source
  into `scratch/xnu-lab/tools/usr/local/bin`. These were built after the kernel;
  the current kernel does not contain embedded CTF. Its DWARF symbols do work.
- LLDB helper scripts generated beside the kernel's debug-symbol bundle.
- VirtualBuddy 2.2.1 extracted locally and its complete code signature verified:
  `scratch/xnu-lab/virtualbuddy/VirtualBuddy.app`. It has not been launched or
  installed in Applications. Its GUI uses Apple's Virtualization.framework.

The kernel links Apple's binary-only VMAPPLE platform archive from KDK 25A353;
it is not a claim that every linked instruction was built from public source.
CoreEntitlements headers are taken as a coherent set from KDK 25E246, including
its real Kernel.h. That cross-version choice has compile/link verification only,
not runtime ABI verification. Historical Apple Security tag Security-55471.14.18
(commit 5437914d400816e369940421d1417d37822a8fbe) supplies libDER headers.

The external Clang VFS overlay removes the unavailable AppleFeatures include
without modifying upstream. An external iBoot header supplies the single 4096-byte
constant used by the inspected public build recipe. That value is a compatibility
assumption from the recipe, not a measurement of this machine. The compiler
adapter suppresses reserved-identifier diagnostics for Apple's implementation
names and leaves unused-set-variable, pointer-cast, GNU constant-folding warnings
visible rather than fatal. A format warning is nonfatal only for prng_random.c.
Other warnings remain errors. No blanket BUILD_WERROR=0 was used.

### Game commands added

```sh
game run fetch-environment
game run extract-kdks
game run prepare-sdk
game run kernel-headers
game run build-firehose
game run build-kernel
game run build-ctf
game run verify-kernel
game run prepare-vm
game run build-collection
```

Use the same GAME_HOME and absolute game executable described below. Builds are
limited to two workers and 120 seconds per invocation, with incremental restart.
The successful link was an incremental continuation after a timeout during LTO.

The fetched release manifest and KDK archives are currently staged inputs, not
redownloaded by these game commands. `fetch-environment` expects release-260.json;
`extract-kdks` expects the two checksummed DMGs. Their original download provenance
is in this session and the paths/hashes in environment.py. A completely unattended
fresh-machine bootstrap is not yet implemented.

### Remaining blockers: this is not yet a running guest

A boot kernel collection was attempted with explicit KDK/repository/kernel paths,
a named `.kdk` bundle, and explicit SDK selection. Host kmutil still rejects the
uninstalled extracted kit with exit 71: it cannot find an installed SDK/KDK
matching build 25A353. An earlier attempt exited 34. The experimental
`--allow-missing-kdk` attempt did not solve it; the command must not be mistaken
for a verified boot recipe. No valid collection was produced and the hand-picked
extension list is not yet validated against a matching guest boot manifest.

There is no macOS guest, restore image, guest developer installation, or successful
custom-kernel boot. The current free space is about 19 GiB on a 45 GiB quota.
VirtualBuddy defaults to a 64 GB guest disk, and a full restore image plus a
macOS development guest and mutant worktrees cannot responsibly be promised in
this remaining allowance. A larger agent-owned volume/quota, or an explicit
location for the guest with sufficient capacity, is needed before downloading a
restore image and allocating a VM. No other volume was used without permission.
A useful allowance is at least 80 GiB additional free space for installation,
SDKs, and workload, with actual usage measured as setup progresses.

The remaining external actions are providing that guest storage and, if kmutil
cannot use isolated discovery, deciding whether to install the verified matching
KDK globally or perform collection creation inside the matching guest. I have
not requested or used root to alter the host. Guest recovery/security-policy
changes also remain yours to approve; host protections stay unchanged.

## Initial result (historical)

The real build generated interfaces and headers and compiled the host setup
tools. An external AvailabilityVersions adapter resolved the first missing
`availability.pl` dependency without changing XNU or the installed SDK.

**No kernel binary has been produced.** Kernel compilation currently fails
because the public macOS 26.2 SDK lacks these include directories:

- `usr/local/include/kernel`
- `usr/local/include`
- `System/Library/Frameworks/Kernel.framework/Versions/A/PrivateHeaders/AppleFeatures`
- `System/Library/Frameworks/Kernel.framework/Versions/A/PrivateHeaders/platform`

The build keeps warnings as errors. It does not create empty header directories,
suppress these errors, invent headers, or pretend a dry run proves compilation.
Other missing headers or link libraries may appear after these are supplied.

No installed KDK directory was found during the initial check. `ctfconvert` and
`ctfmerge` are also absent; XNU disables CTF merging when its tool is missing.
Those absences were not the first fatal kernel-compilation error.

## Layout

Read-only upstream checkouts, generated outputs, and dependency overlay:

```text
pronghorn/source
pronghorn/availability
pronghorn/availability-sdk
pronghorn/build/obj
pronghorn/build/sym
pronghorn/build/dst
```

The upstream source stays clean. Every build supplies explicit OBJROOT, SYMROOT,
and DSTROOT. Nothing is installed into the host's kernel or SDK directories.
`logs/` holds per-invocation logs with command, source revision, combined compiler
output, and final exit/timeout status. Output is displayed live as well.

## Pinned inputs

| Input | Tag | Commit |
| --- | --- | --- |
| XNU | xnu-12377.1.9 | f6217f891ac0bb64f3d375211650a4c1ff8ca1ea |
| AvailabilityVersions | AvailabilityVersions-157.2 | 149b1777f3e8c2133042d8e188f72e3adf6a7110 |

Sources:

- https://github.com/apple-oss-distributions/xnu
- https://github.com/apple-oss-distributions/AvailabilityVersions

AvailabilityVersions is used only for the symbol-aliasing generator. Its public
version table is older than the selected SDK; this adapter is exploratory, not a
claim that it supplies a complete version-matched internal SDK.

The host is macOS 27.2, build 26B5091g, XNU 13432.40.162, with Xcode 26.3 and
macOS SDK 26.2. Public XNU 12377.1.9 is not the host kernel's source version.
Setting RC_DARWIN_KERNEL_VERSION records the public source version; it does not
make source, SDK, drivers, or guest versions compatible.

## Game commands

From this project's directory, use:

```sh
export GAME_HOME={...}
game run test
game run fetch
game run preflight
game run probe
game run build-xnu
```

`fetch` clones pinned public tags if absent and checks their commit identities.
`preflight` logs host, SDK, and tool discovery; it is inventory, not a certificate
that the SDK is complete. `probe` runs upstream make with `-n`. Recursive make and
parse-time shell commands can still execute, so this is not a no-side-effect
sandbox. On a clean tree, upstream's dry-run bootstrap may fail because directories
that it only printed were not created. After real setup, the probe succeeds.

`build-xnu` runs the actual default build, with two workers and a 120-second
wall-clock limit. It sends SIGTERM to the entire build process group on timeout,
then SIGKILL after five more seconds. Timeout exits 124. Nonzero make status is
preserved by the runner; game itself may report that as its own generic failure.
A subsequent invocation reuses outputs; it does not delete the build tree.

For another SDK/KDK or a longer bounded attempt, declare a separate `.game` run
line invoking `python3 -u lab.py build --sdk /absolute/sdk --kdk /absolute/kdk
--seconds N`. The runner accepts those options. No long build has been authorized
or started. Do not point DSTROOT at the host system; it is deliberately fixed here.

Five runner tests cover source identity and cleanliness checks, configuration,
live/file logging, nonzero status preservation, timeout behavior, and argument
limits. They pass through `game run test`. Actual setup and kernel compilation
were also attempted, not mocked. This is not exhaustive test or review coverage.

## What is needed next

The next external input is a compatible development SDK/KDK with the missing
kernel/platform headers, or a vetted public-source recipe that reconstructs those
dependencies in an isolated SDK overlay. A path to an already available kit is
sufficient; credentials should never be supplied to this project. A KDK alone is
not assumed sufficient until its contents and an actual build verify that.

The intended VM guest version must be selected together with available public
source and development files. Reproducing the host's exact 27.2 problem requires
matching components that this public checkout does not currently supply. An older
guest is still useful for build bring-up, but absence of its leak would not clear
the host's newer daemon.

Building a kernel and booting it are separate milestones. No VM was created,
no restore image downloaded, no boot policy changed, and no custom kernel boot
was attempted. The eventual VM must contain full macOS to include Apple's
proprietary fseventsd; building XNU alone does not supply that daemon.

## Safety and provenance boundaries

This project requires no root privileges for its current operations. It makes
no host boot changes, disables no protections, restarts no services, and writes
no files into another checkout. There are no install or boot commands.
The source tree is checked for tracked or untracked modifications before and
after builds. No source patches have been applied.

The runner records upstream revision and command provenance. It does not yet
stamp a finished kernel artifact, because no such artifact exists. No release,
commit, push, package publication, or independent review has occurred.
