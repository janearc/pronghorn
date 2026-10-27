from pathlib import Path
import shutil
import subprocess

import lab

REVISION = "6a2e1a0144e70e875b4586c23da236e0e8d48e77"
SOURCE = lab.WORK / "virtualbuddy-source"
OUTPUT = Path("/Volumes/porter-crush/home/shared/VirtualBuddy-diagnostic-source")


def replace_once(path, old, new):
    content = path.read_text()
    if content.count(old) != 1:
        raise RuntimeError(f"Unexpected upstream context in {path}")
    path.write_text(content.replace(old, new))


def main():
    revision = lab.run(["git", "rev-parse", "HEAD"], cwd=SOURCE)
    dirty = lab.run(["git", "status", "--porcelain", "--untracked-files=all"], cwd=SOURCE)
    if revision.returncode or revision.stdout.strip() != REVISION or dirty.returncode or dirty.stdout.strip():
        raise RuntimeError("Upstream VirtualBuddy identity or cleanliness check failed")
    if OUTPUT.exists():
        raise RuntimeError("Diagnostic source already exists; refusing to overwrite")
    shutil.copytree(SOURCE, OUTPUT, ignore=shutil.ignore_patterns(".git"))
    core = OUTPUT / "VirtualCore/Source/Restore/Installation"
    shutil.copyfile(lab.PROJECT / "RestoreDiagnostics.swift", core / "RestoreDiagnostics.swift")
    standard = core / "VirtualizationRestoreBackend.swift"
    replace_once(standard, "        try await installer.install()\n", """        do {
            try await installer.install()
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            let details = RestoreDiagnostics.describe(error as NSError)
            logger.error("Restore failed: \\(details, privacy: .private)")
            var files: [URL] = []
            do {
                files = [try RestoreDiagnostics.persist(details)]
            } catch {
                logger.error("Failed to save restore diagnostics: \\(error, privacy: .private)")
            }
            throw RestoreFailure(message: details, diagnosticFileURLs: files)
        }
""")
    beta = core / "VirtualInstallationRestoreBackend.swift"
    replace_once(beta, """        } catch let error as DeviceRestoreFailure {
            throw RestoreFailure(
                message: error.localizedDescription,
                diagnosticFileURLs: error.logFileURLs
            )
""", """        } catch let error as DeviceRestoreFailure {
            var details = error.localizedDescription
            if let underlying = error.underlyingError {
                details = "domain=\\(underlying.domain) code=\\(underlying.code)\\n" + details
                if let reason = underlying.failureReason {
                    details += "\\nfailureReason=\\(reason)"
                }
            }
            logger.error("Restore failed: \\(details, privacy: .private)")
            var files = error.logFileURLs
            do {
                files.append(try RestoreDiagnostics.persist(details))
            } catch {
                logger.error("Failed to save restore diagnostics: \\(error, privacy: .private)")
            }
            throw RestoreFailure(message: details, diagnosticFileURLs: files)
""")
    delegate = OUTPUT / "VirtualBuddy/Bootstrap/VirtualBuddyAppDelegate.swift"
    replace_once(delegate,
        '#if BUILDING_NON_MANAGED_RELEASE\n#error("Trying to build for release without using the managed scheme. This build won\'t include managed entitlements. This error is here for Rambo, you may safely comment it out and keep going.")\n#endif\n', "")
    (OUTPUT / "DIAGNOSTIC_BASE_REVISION").write_text(REVISION + "\n")
    print(f"diagnostic_source={OUTPUT}")
    print("Upstream checkout unchanged. No application build has run.")


if __name__ == "__main__":
    main()
