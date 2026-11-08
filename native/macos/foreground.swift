// Experimental one-shot observation. No window titles or content are collected.
import AppKit
import Foundation

let workspace = NSWorkspace.shared
if let app = workspace.frontmostApplication {
    let observation: [String: String] = [
        "bundle_id": app.bundleIdentifier ?? "",
        "name": app.localizedName ?? ""
    ]
    do {
        let data = try JSONSerialization.data(withJSONObject: observation, options: [.sortedKeys])
        FileHandle.standardOutput.write(data)
        FileHandle.standardOutput.write(Data([10]))
    } catch {
        fputs("Could not encode foreground observation\n", stderr)
        exit(1)
    }
} else {
    // An unavailable observation is not a claim that no application was active.
    print("null")
}
