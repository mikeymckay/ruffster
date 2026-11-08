// Experimental visible status companion. It exits if its parent process disappears.
import AppKit
import Darwin
import Foundation

private enum MonitoringState: Equatable {
    case starting
    case active
    case paused

    static let defaultSampleInterval = 15.0
    static let maximumSampleInterval = 3600.0

    static func from(lastHeartbeat: Date?, now: Date, sampleInterval: TimeInterval) -> MonitoringState {
        guard let lastHeartbeat else { return .starting }
        let interval = sampleInterval.isFinite && sampleInterval > 0 && sampleInterval <= maximumSampleInterval
            ? sampleInterval : defaultSampleInterval
        return now.timeIntervalSince(lastHeartbeat) <= max(45, interval * 3 + 5) ? .active : .paused
    }

    static func sampleInterval(from value: String?) -> TimeInterval {
        guard let value, let interval = Double(value), interval.isFinite,
              interval > 0, interval <= maximumSampleInterval else { return defaultSampleInterval }
        return interval
    }

    var menuText: String {
        switch self {
        case .starting: return "Waiting for the first completed sample"
        case .active: return "Monitoring is on"
        case .paused: return "Monitoring is paused"
        }
    }

    var buttonText: String {
        switch self {
        case .starting: return "Monitoring …"
        case .active: return "Monitoring On"
        case .paused: return "Monitoring Paused"
        }
    }

    var accessibilityLabel: String {
        switch self {
        case .starting: return "Monitoring is starting"
        case .active: return "Monitoring is on"
        case .paused: return "Monitoring is paused"
        }
    }

    var accessibilityHelp: String {
        switch self {
        case .starting: return "Waiting for the first completed encrypted sample."
        case .active: return "Ruffster recently saved a sample. This confirms the monitor is running, not whether someone is using the computer."
        case .paused: return "No recent sample was saved. Some time may be missing from the report; let your parent know."
        }
    }
}

final class StatusController: NSObject, NSApplicationDelegate {
    private var item: NSStatusItem?
    private var heading: NSMenuItem?
    private var timer: Timer?
    private var shareProcess: Process?
    private var exportProcess: Process?
    private var exportWindow: NSWindow?
    private var heartbeatSource: DispatchSourceRead?
    private var heartbeatBuffer = Data()
    private var lastHeartbeat: Date?
    private let parent = getppid()
    private let sampleInterval = MonitoringState.sampleInterval(from: ProcessInfo.processInfo.environment["FAMILY_ACTIVITY_SAMPLE_INTERVAL"])
    private let sharePython = ProcessInfo.processInfo.environment["FAMILY_ACTIVITY_SHARE_PYTHON"]
    private let shareDatabase = ProcessInfo.processInfo.environment["FAMILY_ACTIVITY_SHARE_DATABASE"]

    func applicationDidFinishLaunching(_ notification: Notification) {
        let status = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        let menu = NSMenu()
        let heading = NSMenuItem(title: "Ruffster is starting…", action: nil, keyEquivalent: "")
        heading.isEnabled = false
        menu.addItem(heading)
        self.heading = heading
        let details = NSMenuItem(title: "What Ruffster records…", action: #selector(showDetails), keyEquivalent: "")
        details.target = self
        menu.addItem(details)
        if sharePython != nil && shareDatabase != nil {
            menu.addItem(.separator())
            let share = NSMenuItem(title: "Share an encrypted report…", action: #selector(shareReport), keyEquivalent: "")
            share.target = self
            menu.addItem(share)
            let export = NSMenuItem(title: "Save an encrypted report file…", action: #selector(saveEncryptedReport), keyEquivalent: "")
            export.target = self
            menu.addItem(export)
            let stop = NSMenuItem(title: "Stop sharing", action: #selector(stopSharing), keyEquivalent: "")
            stop.target = self
            menu.addItem(stop)
        }
        status.menu = menu
        if let button = status.button {
            button.image = NSImage(systemSymbolName: "pawprint.fill", accessibilityDescription: "Ruffster status")
            button.imagePosition = .imageLeading
        }
        item = status
        startHeartbeatListener()
        refreshIndicator()
        print("READY")
        fflush(stdout)
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in
            guard let self = self else { return }
            if getppid() != self.parent || kill(self.parent, 0) != 0 {
                self.stopSharing()
                self.stopExport()
                NSApplication.shared.terminate(nil)
                return
            }
            self.refreshIndicator()
        }
    }

    private func startHeartbeatListener() {
        let source = DispatchSource.makeReadSource(fileDescriptor: STDIN_FILENO, queue: .main)
        source.setEventHandler { [weak self] in self?.readHeartbeats() }
        heartbeatSource = source
        source.resume()
    }

    private func readHeartbeats() {
        var bytes = [UInt8](repeating: 0, count: 256)
        let count = bytes.withUnsafeMutableBytes { buffer -> Int in
            guard let base = buffer.baseAddress else { return -1 }
            return Darwin.read(STDIN_FILENO, base, buffer.count)
        }
        guard count > 0 else {
            heartbeatSource?.cancel()
            heartbeatSource = nil
            refreshIndicator()
            return
        }
        heartbeatBuffer.append(contentsOf: bytes.prefix(count))
        while let newline = heartbeatBuffer.firstIndex(of: 0x0a) {
            let line = String(decoding: heartbeatBuffer[..<newline], as: UTF8.self)
            heartbeatBuffer.removeSubrange(...newline)
            if line == "HEARTBEAT" {
                lastHeartbeat = Date()
                refreshIndicator()
            }
        }
    }

    private func refreshIndicator() {
        let state = MonitoringState.from(lastHeartbeat: lastHeartbeat, now: Date(), sampleInterval: sampleInterval)
        let button = item?.button
        if shareProcess?.isRunning == true {
            heading?.title = "Sharing a report · \(state.menuText.lowercased())"
            button?.title = state.buttonText
            button?.toolTip = "Ruffster: \(state.menuText). An encrypted report is being shared."
            button?.setAccessibilityLabel("Ruffster. Sharing an encrypted report. \(state.accessibilityLabel).")
        } else {
            heading?.title = "Ruffster · \(state.menuText)"
            button?.title = state.buttonText
            button?.toolTip = "Ruffster: \(state.menuText). If the indicator disappears, the agent may have stopped."
            button?.setAccessibilityLabel("Ruffster. \(state.accessibilityLabel).")
        }
        button?.setAccessibilityHelp(state.accessibilityHelp)
    }

    @objc private func showDetails() {
        let alert = NSAlert()
        alert.messageText = "About Ruffster"
        let processNetwork = ProcessInfo.processInfo.environment["FAMILY_ACTIVITY_PROCESS_NETWORK"] == "1"
            ? " Optional app and service network totals are on. Some traffic may appear under helper apps; websites aren't identified."
            : " Optional app and service network totals are off."
        alert.informativeText = "Ruffster helps your family understand computer use. While you're signed in, it records the name and identifier of the app in front, total network bytes by interface, a private hint when the default router changes, and basic DNS, proxy, and system VPN indicators.\(processNetwork) Website domains are not part of this Mac setup; a separate experimental browser add-on is not connected to this report. The router hint does not show where the computer is, and the router address itself is not saved. Reports are locked on this Mac and can be opened on your parent's computer. Ruffster doesn't record screenshots, typing, messages, microphone, camera, or full website addresses. The menu-bar paw shows when recent samples have been saved. If it says monitoring is paused or disappears, some time may be missing from the report; let your parent know."
        alert.addButton(withTitle: "OK")
        NSApplication.shared.activate(ignoringOtherApps: true)
        alert.runModal()
    }

    // Choose a local IPv4 address from an active Ethernet/Wi-Fi interface.
    // This is only a best effort: unusual networks and VPNs may need another path.
    private func localAddress() -> String? {
        var list: UnsafeMutablePointer<ifaddrs>?
        guard getifaddrs(&list) == 0 else { return nil }
        defer { freeifaddrs(list) }
        var candidates: [(String, String)] = []
        var next = list
        while let current = next {
            let item = current.pointee
            next = item.ifa_next
            guard let addr = item.ifa_addr, addr.pointee.sa_family == UInt8(AF_INET),
                  item.ifa_flags & UInt32(IFF_UP) != 0 else { continue }
            let name = String(cString: item.ifa_name)
            guard name.hasPrefix("en") else { continue }
            var host = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            guard getnameinfo(addr, socklen_t(addr.pointee.sa_len), &host, socklen_t(host.count), nil, 0, NI_NUMERICHOST) == 0 else { continue }
            let address = String(cString: host)
            let parts = address.split(separator: ".").compactMap { Int($0) }
            guard parts.count == 4 else { continue }
            let local = parts[0] == 10 || (parts[0] == 172 && (16...31).contains(parts[1])) ||
                        (parts[0] == 192 && parts[1] == 168) || (parts[0] == 169 && parts[1] == 254)
            if local { candidates.append((name, address)) }
        }
        return candidates.sorted { ($0.0 == "en0" ? 0 : 1, $0.0) < ($1.0 == "en0" ? 0 : 1, $1.0) }.first?.1
    }

    @objc private func shareReport() {
        guard let python = sharePython, let database = shareDatabase else { return }
        if shareProcess?.isRunning == true {
            message("A transfer is already active", "Use Stop sharing before starting another one.")
            return
        }
        guard let address = localAddress() else {
            message("No supported local network found", "Connect to the same local network as your parent and try again.")
            return
        }
        let consent = NSAlert()
        consent.messageText = "Share an encrypted report?"
        consent.informativeText = "This computer will show two digits. Your parent will enter them in the dashboard to receive an encrypted report. Both computers need to be on the same Wi-Fi."
        consent.addButton(withTitle: "Continue")
        consent.addButton(withTitle: "Cancel")
        NSApplication.shared.activate(ignoringOtherApps: true)
        guard consent.runModal() == .alertFirstButtonReturn else { return }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        let frozen = ProcessInfo.processInfo.environment["FAMILY_ACTIVITY_SHARE_FROZEN"] == "1"
        process.arguments = (frozen ? ["share"] : ["-m", "family_activity", "share"]) + ["--db", database, "--host", address]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        do { try process.run() }
        catch { message("Could not start sharing", "The report transfer could not be started."); return }
        shareProcess = process
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.async {
                guard let self, self.shareProcess === process else { return }
                self.shareProcess = nil
                self.refreshIndicator()
            }
        }
        refreshIndicator()
        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            var data = Data()
            let handle = pipe.fileHandleForReading
            while data.count < 2048 && data.filter({ $0 == 10 }).count < 2 {
                guard let byte = try? handle.read(upToCount: 1), !byte.isEmpty else { break }
                data.append(byte)
            }
            let lines = String(data: data, encoding: .utf8)?.split(separator: "\n", omittingEmptySubsequences: true) ?? []
            let code = lines.count >= 2 ? String(lines[1]) : nil
            DispatchQueue.main.async { [weak self] in self?.presentCode(code, process: process) }
        }
    }

    private func presentCode(_ code: String?, process: Process) {
        guard process.isRunning, let code = code, !code.isEmpty else {
            message("Could not start sharing", "The report may be unavailable or the local network may have changed.")
            return
        }
        let alert = NSAlert()
        alert.messageText = "Show these two digits to your parent"
        alert.informativeText = "Your parent will enter them in the dashboard to receive an encrypted report. They are available for about five minutes. Choose Stop sharing in the menu to cancel."
        let text = NSTextField(string: code)
        text.isEditable = false
        text.isSelectable = true
        text.frame = NSRect(x: 0, y: 0, width: 430, height: 24)
        alert.accessoryView = text
        alert.addButton(withTitle: "Copy digits")
        alert.addButton(withTitle: "Cancel transfer")
        NSApplication.shared.activate(ignoringOtherApps: true)
        if alert.runModal() == .alertFirstButtonReturn {
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(code, forType: .string)
        } else {
            stopSharing()
        }
    }

    @objc private func stopSharing() {
        if let process = shareProcess, process.isRunning { process.terminate() }
        shareProcess = nil
        refreshIndicator()
    }

    @objc private func saveEncryptedReport() {
        guard let python = sharePython, let database = shareDatabase else { return }
        if exportProcess?.isRunning == true {
            message("A report copy is already being prepared", "Wait for the current encrypted copy to finish.")
            return
        }
        let consent = NSAlert()
        consent.messageText = "Save an encrypted report file?"
        consent.informativeText = "The file contains encrypted activity records only. It does not include the parent key or PIN. Move it to your parent computer, then choose Open a report file instead in the parent dashboard. This option does not use the local network."
        consent.addButton(withTitle: "Continue")
        consent.addButton(withTitle: "Cancel")
        NSApplication.shared.activate(ignoringOtherApps: true)
        guard consent.runModal() == .alertFirstButtonReturn else { return }

        let panel = NSSavePanel()
        panel.title = "Save an encrypted report for your parent"
        panel.nameFieldStringValue = "ruffster-report.sqlite3"
        panel.prompt = "Save encrypted report"
        panel.canCreateDirectories = true
        guard panel.runModal() == .OK, let destination = panel.url else { return }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: python)
        let frozen = ProcessInfo.processInfo.environment["FAMILY_ACTIVITY_SHARE_FROZEN"] == "1"
        process.arguments = (frozen ? ["export-report"] : ["-m", "family_activity", "export-report"]) +
            ["--db", database, "--output", destination.path]
        if FileManager.default.fileExists(atPath: destination.path) {
            process.arguments?.append("--overwrite")
        }
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        process.terminationHandler = { [weak self] finished in
            DispatchQueue.main.async {
                guard let self, self.exportProcess === finished else { return }
                self.exportWindow?.close()
                self.exportWindow = nil
                self.exportProcess = nil
                if finished.terminationStatus == 0 {
                    self.message("Encrypted report saved", "Move the file to your parent computer, then choose Open a report file instead in the parent dashboard.")
                } else {
                    self.message("Could not save the encrypted report", "Choose another folder with enough free space, then try again.")
                }
            }
        }
        do { try process.run() }
        catch {
            exportProcess = nil
            message("Could not save the encrypted report", "The report copy could not start. Try again or use Share an encrypted report.")
            return
        }
        exportProcess = process
        showExportProgressWindow()
    }

    private func showExportProgressWindow() {
        let content = NSStackView()
        content.orientation = .vertical
        content.alignment = .leading
        content.spacing = 14
        content.edgeInsets = NSEdgeInsets(top: 22, left: 24, bottom: 20, right: 24)
        let title = NSTextField(labelWithString: "Saving an encrypted report copy")
        title.font = .boldSystemFont(ofSize: 15)
        let detail = NSTextField(wrappingLabelWithString: "This can take a little while for a larger report. Keep Ruffster open.")
        detail.setAccessibilityLabel("Preparing the encrypted report file")
        let progress = NSProgressIndicator()
        progress.style = .spinning
        progress.isIndeterminate = true
        progress.startAnimation(nil)
        content.addArrangedSubview(title)
        content.addArrangedSubview(detail)
        content.addArrangedSubview(progress)
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 430, height: 150),
                              styleMask: [.titled], backing: .buffered, defer: false)
        window.title = "Ruffster"
        window.contentView = content
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApplication.shared.activate(ignoringOtherApps: true)
        exportWindow = window
    }

    private func stopExport() {
        if let process = exportProcess, process.isRunning { process.terminate() }
        exportProcess = nil
        exportWindow?.close()
        exportWindow = nil
    }

    private func message(_ title: String, _ text: String) {
        let alert = NSAlert(); alert.messageText = title; alert.informativeText = text
        alert.addButton(withTitle: "OK")
        NSApplication.shared.activate(ignoringOtherApps: true)
        alert.runModal()
    }
}

if CommandLine.arguments.contains("--self-test-state") {
    let now = Date(timeIntervalSince1970: 1_000)
    let starting = MonitoringState.from(lastHeartbeat: nil, now: now, sampleInterval: 1)
    let active = MonitoringState.from(lastHeartbeat: now.addingTimeInterval(-2), now: now, sampleInterval: 1)
    let paused = MonitoringState.from(lastHeartbeat: now.addingTimeInterval(-46), now: now, sampleInterval: 1)
    let invalidInterval = MonitoringState.sampleInterval(from: "inf") == 15 &&
        MonitoringState.sampleInterval(from: "nan") == 15 &&
        MonitoringState.sampleInterval(from: "3600.01") == 15 &&
        MonitoringState.sampleInterval(from: "300") == 300
    let hugeIntervalHeartbeat = MonitoringState.from(lastHeartbeat: now.addingTimeInterval(-51), now: now, sampleInterval: .infinity)
    let visibleLabels = starting.buttonText == "Monitoring …" &&
        active.buttonText == "Monitoring On" && paused.buttonText == "Monitoring Paused"
    let accessibleLabels = starting.accessibilityLabel.contains("starting") &&
        active.accessibilityLabel.contains("on") && paused.accessibilityLabel.contains("paused") &&
        !starting.accessibilityHelp.isEmpty && !active.accessibilityHelp.isEmpty && !paused.accessibilityHelp.isEmpty
    let checks: [(String, Bool)] = [
        ("starting state", starting == .starting),
        ("active state", active == .active),
        ("paused state", paused == .paused),
        ("bounded interval parsing", invalidInterval),
        ("oversized interval becomes stale", hugeIntervalHeartbeat == .paused),
        ("visible state labels", visibleLabels),
        ("accessibility labels and help", accessibleLabels)
    ]
    let failures = checks.filter { !$0.1 }.map { $0.0 }
    if failures.isEmpty {
        exit(0)
    } else {
        fputs("Monitoring status self-check failed: \(failures.joined(separator: ", "))\n", stderr)
        exit(1)
    }
}

let app = NSApplication.shared
let controller = StatusController()
app.delegate = controller
app.setActivationPolicy(.accessory)
app.run()
