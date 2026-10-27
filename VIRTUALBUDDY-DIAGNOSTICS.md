# Private diagnostic VirtualBuddy build

## Source and scope

Fetched upstream main at 6a2e1a0144e70e875b4586c23da236e0e8d48e77.
Its version configuration still says 2.2.1 build 430; tip is not automatically
a separately numbered beta. It contains the newer VirtualInstallation backend.

Original upstream checkout remains unchanged:

```text
/Volumes/porter-crush/home/scratch/xnu-lab/virtualbuddy-source
```

The private diagnostic source copy is:

```text
/Volumes/porter-crush/home/shared/VirtualBuddy-diagnostic-source
```

No changes have been submitted or published. Upstream permits private LLM use;
this is not an upstream contribution.

## Diagnostic behavior

The standard VZMacOSInstaller backend now catches the real error before the UI
reduces it to a localized message. It formats domain, numeric code, description,
failure reason, recovery suggestion, and underlying error chains. Traversal is
bounded to avoid recursive or exceptionally deep chains. Arbitrary userInfo
values are deliberately excluded, rather than dumping potentially sensitive data.

The newer VirtualInstallation backend preserves its existing four restore logs
and adds a diagnostic summary with its transported domain, code, and failure
reason. It does not reconstruct nested error objects already flattened across
XPC, and does not claim to do so.

Both paths create a per-failure log in the app's temporary directory under
VirtualBuddy-RestoreDiagnostics. Directory mode is 0700 and file mode 0600.
These URLs are attached to the existing restore-failure log-export mechanism.
The error summary is also passed to the existing failure UI. Unified-log entries
are marked private, not public. Error descriptions can still contain sensitive
paths or server text; review saved logs before sharing them.

Cancellation remains cancellation, not a fabricated installation failure.
Logging failure does not replace the original installation diagnosis.

## Tests and game integration

From xnu-lab with GAME_HOME set:

```sh
game run build-restore-diagnostics-tests
game run test-restore-diagnostics
game run prepare-virtualbuddy-diagnostics
```

Standalone Swift diagnostics tests pass with compiler warnings treated as errors.
They cover nested MobileRestore 3194 reporting, reasons and recovery suggestions,
multiple/repeated underlying errors, depth limits, exclusion of arbitrary
credential-like metadata, file contents, and private file permissions.
The Python overlay generator checks exact source context, pinned revision,
clean upstream status, and refuses to overwrite an existing staged source copy.

These are helper-level tests, not an application build or end-to-end GUI test.
The existing nine Python orchestration tests also pass.

## Application build completed

Jane explicitly authorized xcodebuild. `game run build-virtualbuddy` successfully
built the regular Release scheme using the selected Xcode-beta.app and macOS 27
SDK, with two workers. The tip source still labels itself 2.2.1 (430); this is a
private tip build, not an official numbered beta release.

The first signing-enabled attempt required a provisioning profile for upstream's
USB accessory entitlement. The build now runs without Xcode signing, followed by
`game run sign-virtualbuddy`, which signs nested code inside out ad hoc. The main
app keeps virtualization and audio entitlements but omits restricted USB accessory
and managed-network entitlements. USB passthrough and managed-network features
are not supported in this local build. No signing identities or credentials were
read. Non-managed Release already disables upstream's managed XPC team checks.

The upstream maintainer's explicit non-managed-release compile-time reminder was
removed only in the staged private source, as its message permits. The overlay
generator reproduces that removal. The pristine upstream checkout is unchanged.

Verified binary:

```text
/Volumes/porter-crush/home/shared/VirtualBuddy-Diagnostic.app
```

Full deep/strict code-signature verification passed. Diagnostic helper tests and
nine Python tests pass. A launch attempt with `--help` entered the GUI rather
than providing CLI help; it stayed alive until the 15-second test timeout and
was terminated by the test. This does not establish an end-to-end installation
or XPC restore test. A fresh install failure in the GUI remains the runtime test.
No running GUI process was intentionally left behind.

Build output: `logs/virtualbuddy-build.log`.
The unmodified `shared/VirtualBuddy.app` remains untouched. Quit it before opening
the diagnostic copy, since both use the upstream application bundle identifier.
The diagnostic app uses the same existing app preferences/library; no preference
files were edited by the agent.
