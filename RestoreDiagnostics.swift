import Foundation

struct RestoreDiagnostics {
    static func describe(_ error: NSError) -> String {
        var visited = Set<ObjectIdentifier>()
        return describe(error, depth: 0, visited: &visited)
    }

    private static func describe(_ error: NSError, depth: Int,
                                 visited: inout Set<ObjectIdentifier>) -> String {
        guard depth < 16, visited.insert(ObjectIdentifier(error)).inserted else {
            return "Underlying error chain truncated."
        }
        var lines = ["domain=\(error.domain) code=\(error.code)",
                     "description=\(error.localizedDescription)"]
        if let reason = error.localizedFailureReason {
            lines.append("failureReason=\(reason)")
        }
        if let suggestion = error.localizedRecoverySuggestion {
            lines.append("recoverySuggestion=\(suggestion)")
        }
        if let child = error.userInfo[NSUnderlyingErrorKey] as? NSError {
            lines.append("underlying:\n" + describe(child, depth: depth + 1, visited: &visited))
        }
        if let children = error.userInfo["NSMultipleUnderlyingErrors"] as? [NSError] {
            for child in children.prefix(16) {
                lines.append("underlying:\n" + describe(child, depth: depth + 1, visited: &visited))
            }
        }
        return lines.joined(separator: "\n")
    }

    static func persist(_ details: String) throws -> URL {
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("VirtualBuddy-RestoreDiagnostics", isDirectory: true)
        try FileManager.default.createDirectory(at: directory,
            withIntermediateDirectories: true, attributes: [.posixPermissions: 0o700])
        let url = directory.appendingPathComponent("restore-\(UUID().uuidString).log")
        let contents = "date=\(ISO8601DateFormatter().string(from: Date()))\n\(details)\n"
        try contents.write(to: url, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
        return url
    }
}
