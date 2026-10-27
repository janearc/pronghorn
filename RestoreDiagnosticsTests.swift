import Foundation

@main
struct RestoreDiagnosticsTests {
    static func main() throws {
        let inner = NSError(domain: "com.apple.MobileDevice.MobileRestore", code: 3194,
            userInfo: [NSLocalizedDescriptionKey: "Declined to authorize restore."])
        let outer = NSError(domain: "VZErrorDomain", code: 10007,
            userInfo: [NSLocalizedDescriptionKey: "Installation failed.",
                       NSLocalizedFailureReasonErrorKey: "Restore rejected.",
                       NSLocalizedRecoverySuggestionErrorKey: "Use a supported image.",
                       NSUnderlyingErrorKey: inner, "credential": "do-not-log"])
        let details = RestoreDiagnostics.describe(outer)
        precondition(details.contains("domain=VZErrorDomain code=10007"))
        precondition(details.contains("domain=com.apple.MobileDevice.MobileRestore code=3194"))
        precondition(details.contains("failureReason=Restore rejected."))
        precondition(details.contains("recoverySuggestion=Use a supported image."))
        precondition(!details.contains("do-not-log"))
        let multiple = NSError(domain: "multiple", code: 1,
            userInfo: ["NSMultipleUnderlyingErrors": [inner, inner]])
        precondition(RestoreDiagnostics.describe(multiple).contains("truncated"))
        var nested = inner
        for _ in 0..<20 {
            nested = NSError(domain: "nested", code: 2,
                             userInfo: [NSUnderlyingErrorKey: nested])
        }
        precondition(RestoreDiagnostics.describe(nested).contains("truncated"))
        let url = try RestoreDiagnostics.persist(details)
        defer { try? FileManager.default.removeItem(at: url) }
        let stored = try String(contentsOf: url, encoding: .utf8)
        precondition(stored.contains(details))
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        precondition((attributes[.posixPermissions] as? NSNumber)?.intValue == 0o600)
        print("restore diagnostics tests passed")
    }
}
