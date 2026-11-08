// Experimental developer setup shell. It does not bundle a Python runtime.
// A future signed app must supply verified, self-contained runtime paths.
import AppKit
import Foundation

struct Runtime {
    let python: String
    let source: String
    let foreground: String
    let status: String
    let frozen: Bool

    init?(_ arguments: [String], frozen: Bool = false) {
        guard arguments.count == 5 else { return nil }
        let paths = Array(arguments.dropFirst())
        guard paths.allSatisfy({ $0.hasPrefix("/") }),
              FileManager.default.isExecutableFile(atPath: paths[0]),
              (frozen ? FileManager.default.fileExists(atPath: paths[1]) : FileManager.default.fileExists(atPath: paths[1] + "/family_activity/__main__.py")),
              FileManager.default.isExecutableFile(atPath: paths[2]),
              FileManager.default.isExecutableFile(atPath: paths[3]) else { return nil }
        python = paths[0]; source = paths[1]; foreground = paths[2]; status = paths[3]; self.frozen = frozen
    }
}

final class SetupController: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private let runtime: Runtime
    private var parentWindow: NSWindow?
    private var parentProcess: Process?
    private var parentPipe: Pipe?
    private var dashboardURL: URL?
    private var dashboardStatus: NSTextField?
    private var dashboardOpenButton: NSButton?
    private var dashboardStopButton: NSButton?
    private var pairingProcess: Process?
    private var pairingResult: (Process, Data)?
    private var welcomeWindow: NSWindow?
    private var operationProcess: Process?
    private var operationWindow: NSWindow?
    private var installConfirmationButton: NSButton?
    init(runtime: Runtime) { self.runtime = runtime }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApplication.shared.activate(ignoringOtherApps: true)
        showWelcomeWindow()
    }

    private func showWelcomeWindow() {
        func heading(_ text: String) -> NSTextField {
            let field = NSTextField(labelWithString: text)
            field.font = .systemFont(ofSize: 14, weight: .semibold)
            field.setAccessibilityLabel(text)
            return field
        }
        func paragraph(_ text: String, size: CGFloat = 13) -> NSTextField {
            let field = NSTextField(wrappingLabelWithString: text)
            field.font = .systemFont(ofSize: size)
            field.maximumNumberOfLines = 0
            field.usesSingleLineMode = false
            field.setAccessibilityLabel(text)
            return field
        }

        let content = NSView()
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 13
        stack.translatesAutoresizingMaskIntoConstraints = false

        let eyebrow = NSTextField(labelWithString: "FAMILY ACTIVITY  ·  EARLY PREVIEW")
        eyebrow.font = .systemFont(ofSize: 11, weight: .bold)
        eyebrow.textColor = .secondaryLabelColor
        let title = NSTextField(wrappingLabelWithString: "A clearer picture, shared together.")
        title.font = .systemFont(ofSize: 27, weight: .bold)
        title.maximumNumberOfLines = 2
        title.usesSingleLineMode = false
        let introduction = paragraph("Family Activity helps parents and children review how this computer is being used. Set it up together, and keep the monitoring indicator visible.", size: 15)

        let readiness = NSBox()
        readiness.boxType = .primary
        readiness.title = "Preview build"
        readiness.titlePosition = .atTop
        readiness.contentViewMargins = NSSize(width: 12, height: 10)
        readiness.contentView = paragraph("This version is not ready for everyday family use. It cannot detect tampering, and its readings have important limits.")

        let collected = paragraph("Foreground app names and identifiers; total network-interface bytes; reduced DNS, proxy, and system VPN indicators; and a pseudonymous hint when the default router changes. Network bytes are not attributed to apps or websites.")
        let excluded = paragraph("No screenshots, keystrokes, message contents, microphone, camera, or full website URLs. The optional browser experiment is not included in this Mac setup.")
        let disclosure = paragraph("A visible menu-bar indicator shows monitoring status. Activity records are encrypted to a key held by the parent. Router hints do not identify a location, and unknown or missing observations do not explain why they occurred.")

        stack.addArrangedSubview(eyebrow)
        stack.addArrangedSubview(title)
        stack.addArrangedSubview(introduction)
        stack.addArrangedSubview(readiness)
        stack.addArrangedSubview(heading("What this preview records"))
        stack.addArrangedSubview(collected)
        stack.addArrangedSubview(heading("What it never records"))
        stack.addArrangedSubview(excluded)
        stack.addArrangedSubview(disclosure)

        let buttons = NSStackView()
        buttons.orientation = .horizontal
        buttons.alignment = .centerY
        buttons.spacing = 10
        let dashboard = NSButton(title: "Open parent dashboard", target: self, action: #selector(openDashboardFromWelcome))
        dashboard.bezelStyle = .rounded
        dashboard.keyEquivalent = "\r"
        let childSetup = NSButton(title: "Set up this Mac together…", target: self, action: #selector(setupChildFromWelcome))
        childSetup.bezelStyle = .rounded
        let more = NSButton(title: "More options…", target: self, action: #selector(moreOptionsFromWelcome))
        more.bezelStyle = .rounded
        buttons.addArrangedSubview(dashboard)
        buttons.addArrangedSubview(childSetup)
        buttons.addArrangedSubview(more)
        stack.addArrangedSubview(buttons)

        content.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 28),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -28),
            stack.topAnchor.constraint(equalTo: content.topAnchor, constant: 24),
            stack.bottomAnchor.constraint(equalTo: content.bottomAnchor, constant: -24),
            title.widthAnchor.constraint(equalTo: stack.widthAnchor),
            introduction.widthAnchor.constraint(equalTo: stack.widthAnchor),
            readiness.widthAnchor.constraint(equalTo: stack.widthAnchor),
            collected.widthAnchor.constraint(equalTo: stack.widthAnchor),
            excluded.widthAnchor.constraint(equalTo: stack.widthAnchor),
            disclosure.widthAnchor.constraint(equalTo: stack.widthAnchor),
        ])

        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 680, height: 650),
                              styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "Family Activity"
        window.contentView = content
        window.isReleasedWhenClosed = false
        window.center()
        window.makeKeyAndOrderFront(nil)
        welcomeWindow = window
    }

    @objc private func openDashboardFromWelcome() {
        showParentDashboardWindow()
        startParentDashboard()
    }

    @objc private func setupChildFromWelcome() { choosePublicKey() }

    @objc private func moreOptionsFromWelcome() { showMoreOptions() }

    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if sender === welcomeWindow { return true }
        guard let process = parentProcess, process.isRunning else { return true }
        let confirm = NSAlert()
        confirm.messageText = "Stop the parent dashboard and close?"
        confirm.informativeText = "The local browser page will stop responding until you start the dashboard again. Your report and parent access will remain on this Mac."
        confirm.addButton(withTitle: "Stop dashboard and close")
        confirm.addButton(withTitle: "Cancel")
        guard confirm.runModal() == .alertFirstButtonReturn else { return false }
        process.terminate()
        return true
    }

    private func showMoreOptions() {
        let options = NSAlert()
        options.messageText = "More Family Activity options"
        options.informativeText = "Remove a previously installed agent or quit setup."
        options.addButton(withTitle: "Remove existing agent…")
        options.addButton(withTitle: "Quit")
        if options.runModal() == .alertFirstButtonReturn { removeAgent() }
    }

    private func showParentDashboardWindow() {
        let content = NSView()
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .leading
        stack.spacing = 14
        let title = NSTextField(labelWithString: "Your family dashboard")
        title.font = .systemFont(ofSize: 22, weight: .bold)
        let explanation = NSTextField(wrappingLabelWithString: "The dashboard opens in your browser and stays on this Mac. Reports are encrypted on disk; the parent-only PIN opens them. This early preview is for disclosed testing only.")
        explanation.maximumNumberOfLines = 4
        let status = NSTextField(wrappingLabelWithString: "Starting the local dashboard…")
        status.maximumNumberOfLines = 3
        let open = NSButton(title: "Open dashboard", target: self, action: #selector(openParentDashboard))
        open.isEnabled = false
        let stop = NSButton(title: "Stop dashboard", target: self, action: #selector(stopParentDashboard))
        stop.isEnabled = false
        let buttons = NSStackView(views: [open, stop])
        buttons.orientation = .horizontal
        buttons.alignment = .centerY
        buttons.spacing = 10
        stack.addArrangedSubview(title)
        stack.addArrangedSubview(explanation)
        stack.addArrangedSubview(status)
        stack.addArrangedSubview(buttons)
        stack.translatesAutoresizingMaskIntoConstraints = false
        content.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 28),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -28),
            stack.topAnchor.constraint(equalTo: content.topAnchor, constant: 26),
            stack.bottomAnchor.constraint(lessThanOrEqualTo: content.bottomAnchor, constant: -26),
            explanation.widthAnchor.constraint(equalTo: stack.widthAnchor),
            status.widthAnchor.constraint(equalTo: stack.widthAnchor),
        ])
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 560, height: 260),
                              styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "Family Activity for parents"
        window.contentView = content
        window.delegate = self
        window.isReleasedWhenClosed = false
        parentWindow = window
        dashboardStatus = status
        dashboardOpenButton = open
        dashboardStopButton = stop
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApplication.shared.activate(ignoringOtherApps: true)
    }

    private func startParentDashboard() {
        if let process = parentProcess, process.isRunning {
            if let url = dashboardURL { NSWorkspace.shared.open(url) }
            return
        }
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: runtime.python)
        process.arguments = runtime.frozen ? ["parent", "--no-browser"] : ["-m", "family_activity", "parent", "--no-browser"]
        process.currentDirectoryURL = URL(fileURLWithPath: runtime.source, isDirectory: true)
        process.standardOutput = pipe
        process.standardError = FileHandle.nullDevice
        process.standardInput = FileHandle.nullDevice
        do {
            try process.run()
            parentProcess = process
            parentPipe = pipe
            dashboardURL = nil
            dashboardStatus?.stringValue = "Starting the local dashboard…"
            dashboardStopButton?.isEnabled = true
            dashboardOpenButton?.isEnabled = false
            process.terminationHandler = { [weak self] ended in
                DispatchQueue.main.async {
                    guard let self, self.parentProcess === ended else { return }
                    self.parentProcess = nil
                    self.parentPipe = nil
                    self.dashboardURL = nil
                    self.dashboardStatus?.stringValue = "The parent dashboard has stopped. Start it again when you need it."
                    self.dashboardOpenButton?.title = "Start dashboard"
                    self.dashboardOpenButton?.isEnabled = true
                    self.dashboardStopButton?.isEnabled = false
                }
            }
            let output = pipe.fileHandleForReading
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in
                var buffer = Data()
                while true {
                    let next = output.availableData
                    if next.isEmpty { break }
                    buffer.append(next)
                    while let newline = buffer.range(of: Data([0x0a])) {
                        let line = String(decoding: buffer[..<newline.lowerBound], as: UTF8.self)
                            .trimmingCharacters(in: .whitespacesAndNewlines)
                        buffer.removeSubrange(..<newline.upperBound)
                        guard let url = URL(string: line), url.scheme == "http",
                              url.host == "127.0.0.1", url.port != nil else { continue }
                        DispatchQueue.main.async {
                            guard let self, self.parentProcess === process else { return }
                            self.dashboardURL = url
                            self.dashboardStatus?.stringValue = "The local dashboard is open in your browser. Use Stop dashboard here to close it."
                            self.dashboardOpenButton?.title = "Open dashboard"
                            self.dashboardOpenButton?.isEnabled = true
                            NSWorkspace.shared.open(url)
                        }
                    }
                }
            }
        } catch {
            dashboardStatus?.stringValue = "Could not start the parent dashboard. Check the preview installation and try again."
            dashboardOpenButton?.title = "Start dashboard"
            dashboardOpenButton?.isEnabled = true
            dashboardStopButton?.isEnabled = false
        }
    }

    @objc private func openParentDashboard() { startParentDashboard() }

    @objc private func stopParentDashboard() {
        guard let process = parentProcess, process.isRunning else { return }
        dashboardStatus?.stringValue = "Closing the local dashboard…"
        dashboardStopButton?.isEnabled = false
        process.terminate()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard operationProcess != nil else { return .terminateNow }
        message("Family Activity is finishing a setup action", "Wait for the current setup or removal action to finish before closing the app.")
        return .terminateCancel
    }

    private func choosePublicKey() {
        let choice = NSAlert()
        choice.messageText = "Connect this Mac to the parent computer"
        choice.informativeText = "The parent can show two digits in their Family Activity dashboard while both computers are on the same Wi-Fi. You can also choose a connection file. The parent's private access stays on their computer."
        choice.addButton(withTitle: "Enter two digits")
        choice.addButton(withTitle: "Choose connection file…")
        choice.addButton(withTitle: "Cancel")
        switch choice.runModal() {
        case .alertFirstButtonReturn: fetchParentKey()
        case .alertSecondButtonReturn: choosePublicKeyFile()
        default: break
        }
    }

    private func choosePublicKeyFile() {
        let panel = NSOpenPanel()
        panel.title = "Choose the connection file from your parent"
        panel.message = "Select the Family Activity connection file your parent downloaded. Do not select the encrypted recovery copy."
        panel.canChooseFiles = true; panel.canChooseDirectories = false; panel.allowsMultipleSelection = false
        guard panel.runModal() == .OK, let key = panel.url else { return }
        reviewAndInstall(key)
    }

    private func fetchParentKey() {
        let alert = NSAlert()
        alert.messageText = "Connect to the parent's computer"
        alert.informativeText = "Enter the two digits shown in the parent's dashboard. Keep both computers on the same Wi-Fi. The parent's PIN is never entered here."
        let field = NSTextField(string: "")
        field.placeholderString = "Two digits from the parent"
        field.frame = NSRect(x: 0, y: 0, width: 460, height: 28)
        alert.accessoryView = field
        alert.addButton(withTitle: "Connect to parent")
        alert.addButton(withTitle: "Cancel")
        guard alert.runModal() == .alertFirstButtonReturn else { return }
        let code = field.stringValue.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !code.isEmpty else {
            message("Enter the two digits", "Ask the parent to show the digits in their dashboard.")
            return
        }
        guard code.utf8.count == 2, code.utf8.allSatisfy({ $0 >= 48 && $0 <= 57 }) else {
            message("Check the two digits", "Enter the digits shown in the parent's dashboard. If they are not working, choose the connection file instead.")
            return
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: runtime.python)
        process.arguments = runtime.frozen ? ["fetch-public-key"] : ["-m", "family_activity", "fetch-public-key"]
        process.currentDirectoryURL = URL(fileURLWithPath: runtime.source, isDirectory: true)
        let input = Pipe(), output = Pipe()
        process.standardInput = input
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            pairingProcess = process
            input.fileHandleForWriting.write(Data((code + "\n").utf8))
            try? input.fileHandleForWriting.close()

            let progress = NSProgressIndicator(frame: NSRect(x: 0, y: 0, width: 28, height: 28))
            progress.style = .spinning
            progress.setAccessibilityLabel("Connecting to the parent's Mac")
            progress.startAnimation(nil)
            let waiting = NSAlert()
            waiting.messageText = "Connecting to the parent's Mac…"
                waiting.informativeText = "Connecting to the parent's computer and receiving the report-encryption setup. You can cancel at any time. If the code has expired or was already used, ask them to create another."
            waiting.accessoryView = progress
            waiting.addButton(withTitle: "Cancel")
            pairingResult = nil

            DispatchQueue.global(qos: .userInitiated).async { [weak self] in
                let keyData = output.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                DispatchQueue.main.async {
                    guard let self, self.pairingProcess === process else { return }
                    self.pairingResult = (process, keyData)
                    NSApplication.shared.stopModal(withCode: .continue)
                }
            }
            let response = waiting.runModal()
            if response == .alertFirstButtonReturn {
                pairingProcess?.terminate()
                pairingProcess = nil
                pairingResult = nil
                return
            }
            guard let (finished, keyData) = pairingResult, finished === process else {
                pairingProcess = nil
                message("Could not connect to the parent's Mac", "Check that both computers are on the same local network and the two digits are current. The parent can show new digits or share the connection file instead.")
                return
            }
            pairingProcess = nil
            pairingResult = nil
            let marker = Data("FAMILY-ACTIVITY-PUBLIC-KEY-V1\n".utf8)
            guard process.terminationStatus == 0, keyData.count == marker.count + 32,
                  keyData.starts(with: marker) else {
                message("Could not connect to the parent's Mac", "Check that both computers are on the same local network and the two digits are current. The parent can show new digits or share the connection file instead.")
                return
            }
            let temporaryDirectory = FileManager.default.temporaryDirectory
                .appendingPathComponent("FamilyActivityPairing-\(UUID().uuidString)", isDirectory: true)
            do {
                try FileManager.default.createDirectory(at: temporaryDirectory, withIntermediateDirectories: true)
                let key = temporaryDirectory.appendingPathComponent("family-public.key")
                try keyData.write(to: key, options: .atomic)
                reviewAndInstall(key, temporaryDirectory: temporaryDirectory)
            } catch {
                try? FileManager.default.removeItem(at: temporaryDirectory)
                message("Could not prepare the parent connection", "Try the two digits again or choose the connection file instead.")
            }
        } catch {
            pairingProcess = nil
            message("Could not connect to the parent's Mac", "Check the two digits and local network, then try again. You can also choose the connection file instead.")
        }
    }

    private func reviewAndInstall(_ key: URL, temporaryDirectory: URL? = nil) {
        var cleanupWhenComplete = false
        defer {
            if !cleanupWhenComplete, let temporaryDirectory {
                try? FileManager.default.removeItem(at: temporaryDirectory)
            }
        }
        let marker = Data("FAMILY-ACTIVITY-PUBLIC-KEY-V1\n".utf8)
        let size = (try? FileManager.default.attributesOfItem(atPath: key.path)[.size] as? NSNumber)?.intValue
        guard size == marker.count + 32,
              let data = try? Data(contentsOf: key), data.starts(with: marker) else {
                message("That doesn't look like a Family Activity connection file", "Choose the file downloaded from the parent's dashboard, or enter the two digits shown there. Do not select the encrypted recovery copy.")
            return
        }
        let review = NSAlert()
        review.messageText = "Set up this Mac together?"
        review.informativeText = "Read what this preview records, choose how long to keep detailed records, and explain the monitoring to the child before setup."
        let disclosureText = NSTextView()
        disclosureText.frame = NSRect(x: 0, y: 0, width: 460, height: 190)
        disclosureText.isEditable = false
        disclosureText.isSelectable = true
        disclosureText.drawsBackground = false
        disclosureText.isVerticallyResizable = true
        disclosureText.isHorizontallyResizable = false
        disclosureText.textContainer?.widthTracksTextView = true
        disclosureText.textContainer?.containerSize = NSSize(width: 430, height: .greatestFiniteMagnitude)
        disclosureText.textContainerInset = NSSize(width: 6, height: 6)
        disclosureText.string = """
        While this account is signed in, Family Activity samples foreground app names, network-interface traffic totals, a pseudonymous hint when the default router changes, and basic DNS, proxy, and VPN settings. Network bytes are not attributed to apps or websites. The router hint is not a location, and the raw router address is not saved.

        It does not record screenshots, keystrokes, message contents, microphone, camera, or full website addresses. Website domains are not included in this Mac setup.

        The menu-bar status icon must stay visible to the child. Reports are locked on this Mac and can be opened on the parent's computer. Keep this app in its current location; moving it may stop monitoring.

        Choose the maximum time to keep detailed records here. Records are removed while monitoring runs; calendar-day rounding may remove them up to a day before that limit. Removing monitoring keeps the encrypted report and Family Activity connection details unless you choose to delete them. Reports already shared elsewhere and other copies are not affected.
        """
        disclosureText.setAccessibilityLabel("Family Activity collection and retention details")
        let disclosureScroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 460, height: 190))
        disclosureScroll.hasVerticalScroller = true
        disclosureScroll.hasHorizontalScroller = false
        disclosureScroll.documentView = disclosureText
        disclosureScroll.setAccessibilityLabel("Scrollable collection and retention details")
        let retention = NSPopUpButton(frame: NSRect(x: 0, y: 0, width: 230, height: 26), pullsDown: false)
        for days in [7, 30, 90, 180, 365] {
            retention.addItem(withTitle: "\(days) days")
            retention.lastItem?.representedObject = days
        }
        retention.selectItem(withTitle: "30 days")
        retention.setAccessibilityLabel("Maximum detailed record retention")
        let retentionRow = NSStackView(views: [NSTextField(labelWithString: "Keep detailed records for"), retention])
        retentionRow.orientation = .horizontal
        retentionRow.alignment = .centerY
        retentionRow.spacing = 10
        let acknowledgement = NSButton(checkboxWithTitle: "I have explained this monitoring to the child, and they understand it will run on this account.", target: self, action: #selector(updateSetupConfirmation(_:)))
        acknowledgement.setAccessibilityLabel("Confirm the child understands monitoring will run on this account")
        acknowledgement.setAccessibilityHelp("Read the collection details and discuss them with the child before enabling setup.")
        acknowledgement.cell?.wraps = true
        acknowledgement.cell?.usesSingleLineMode = false
        let accessory = NSStackView(views: [disclosureScroll, retentionRow, acknowledgement])
        accessory.orientation = .vertical
        accessory.alignment = .leading
        accessory.spacing = 10
        disclosureScroll.translatesAutoresizingMaskIntoConstraints = false
        acknowledgement.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            disclosureScroll.widthAnchor.constraint(equalToConstant: 460),
            disclosureScroll.heightAnchor.constraint(equalToConstant: 190),
            acknowledgement.widthAnchor.constraint(equalToConstant: 460),
        ])
        review.accessoryView = accessory
        let installButton = review.addButton(withTitle: "Install for this account")
        review.addButton(withTitle: "Cancel")
        installConfirmationButton = installButton
        installConfirmationButton?.isEnabled = false
        let response = review.runModal()
        installConfirmationButton = nil
        guard response == .alertFirstButtonReturn, acknowledgement.state == .on else { return }
        let retentionDays = retention.selectedItem?.representedObject as? Int ?? 30
        let arguments = ["-m", "family_activity", "mac-install", "--public-key", key.path,
                         "--source-directory", runtime.source, "--foreground-helper", runtime.foreground,
                         "--status-helper", runtime.status, "--retention-days", String(retentionDays), "--disclosed"]
        cleanupWhenComplete = temporaryDirectory != nil
        runWithProgress(arguments, title: "Setting up this Mac…",
                        detail: "Registering monitoring for this account. Keep Family Activity open.") { [weak self] succeeded, detail in
            if let temporaryDirectory { try? FileManager.default.removeItem(at: temporaryDirectory) }
            guard let self else { return }
            if succeeded {
                self.message("Agent registered", "Check that the Family Activity menu-bar indicator is visible. If it is not, remove the agent and do not use the preview.")
            } else {
                self.message("Installation did not complete", self.failureText(detail, fallback: "Check the selected connection file and try again. No existing report was intentionally removed."))
            }
        }
    }

    @objc private func updateSetupConfirmation(_ sender: NSButton) {
        installConfirmationButton?.isEnabled = sender.state == .on
    }

    private func removeAgent() {
        let confirm = NSAlert()
        confirm.messageText = "Remove the Family Activity agent?"
        confirm.informativeText = "Monitoring will stop and won't start at sign-in. The encrypted report and Family Activity connection details will stay on this computer. Removing the app does not delete backups or copies."
        confirm.addButton(withTitle: "Remove agent and keep report")
        confirm.addButton(withTitle: "Delete agent and local report…")
        confirm.addButton(withTitle: "Cancel")
        let response = confirm.runModal()
        guard response == .alertFirstButtonReturn || response == .alertSecondButtonReturn else { return }
        let deleteData = response == .alertSecondButtonReturn
        if deleteData {
            let final = NSAlert()
            final.alertStyle = .critical
            final.messageText = "Permanently delete this computer's local report?"
        final.informativeText = "This removes the encrypted activity report and Family Activity connection details from this account. The report on this computer will no longer be available. Reports already imported to a parent computer, backups, and other copies are not affected."
            final.addButton(withTitle: "Delete local report")
            final.addButton(withTitle: "Cancel")
            guard final.runModal() == .alertFirstButtonReturn else { return }
        }
        let arguments = deleteData ? ["-m", "family_activity", "mac-uninstall", "--delete-data"] : ["-m", "family_activity", "mac-uninstall"]
        runWithProgress(arguments, title: "Removing Family Activity…",
                        detail: "Stopping this account's monitoring agent. Reports are kept unless you chose to delete this Mac's local copy.") { [weak self] succeeded, detail in
            guard let self else { return }
            if succeeded {
                self.message("Monitoring removed", deleteData ? "The local encrypted report and connection details were deleted." : "The encrypted report and connection details remain in this account's Family Activity folder.")
            } else {
                let fallback = deleteData ? "The agent may have stopped, but the local report could not be fully deleted. Check the Family Activity data folder." : "The installation may have changed or the agent may not be installed. No report was deleted."
                self.message("Could not remove the agent", self.failureText(detail, fallback: fallback))
            }
        }
    }

    private func runWithProgress(_ arguments: [String], title: String, detail: String,
                                 completion: @escaping (Bool, String?) -> Void) {
        guard operationProcess == nil else {
            completion(false, "Another setup action is still running. Wait for it to finish, then try again.")
            return
        }
        let process = Process()
        process.executableURL = URL(fileURLWithPath: runtime.python)
        process.arguments = runtime.frozen ? Array(arguments.dropFirst(2)) : arguments
        process.currentDirectoryURL = URL(fileURLWithPath: runtime.source, isDirectory: true)
        process.standardOutput = FileHandle.nullDevice
        let errors = Pipe()
        process.standardError = errors
        process.standardInput = FileHandle.nullDevice
        do {
            try process.run()
            operationProcess = process
        } catch {
            completion(false, error.localizedDescription)
            return
        }

        let content = NSView()
        let stack = NSStackView()
        stack.orientation = .vertical
        stack.alignment = .centerX
        stack.spacing = 14
        stack.translatesAutoresizingMaskIntoConstraints = false
        let progress = NSProgressIndicator(frame: NSRect(x: 0, y: 0, width: 28, height: 28))
        progress.style = .spinning
        progress.setAccessibilityLabel(title)
        progress.startAnimation(nil)
        let heading = NSTextField(labelWithString: title)
        heading.font = .systemFont(ofSize: 16, weight: .semibold)
        let explanation = NSTextField(wrappingLabelWithString: detail)
        explanation.maximumNumberOfLines = 3
        explanation.setAccessibilityLabel(detail)
        stack.addArrangedSubview(progress)
        stack.addArrangedSubview(heading)
        stack.addArrangedSubview(explanation)
        content.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: content.leadingAnchor, constant: 24),
            stack.trailingAnchor.constraint(equalTo: content.trailingAnchor, constant: -24),
            stack.centerYAnchor.constraint(equalTo: content.centerYAnchor),
            explanation.widthAnchor.constraint(equalTo: stack.widthAnchor),
        ])
        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 460, height: 190),
                              styleMask: [.titled], backing: .buffered, defer: false)
        window.title = "Family Activity"
        window.contentView = content
        window.center()
        window.makeKeyAndOrderFront(nil)
        operationWindow = window
        NSApplication.shared.activate(ignoringOtherApps: true)

        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let errorData = errors.fileHandleForReading.readDataToEndOfFile()
            process.waitUntilExit()
            let errorMessage = String(decoding: errorData, as: UTF8.self)
                .split(whereSeparator: \.isNewline).last.map(String.init)
            let succeeded = process.terminationStatus == 0
            DispatchQueue.main.async {
                guard let self, self.operationProcess === process else { return }
                self.operationProcess = nil
                self.operationWindow?.close()
                self.operationWindow = nil
                completion(succeeded, errorMessage)
            }
        }
    }

    private func failureText(_ detail: String?, fallback: String) -> String {
        guard let detail, !detail.isEmpty else { return fallback }
        let userMessage = detail.components(separatedBy: "error: ").last ?? detail
        return "\(userMessage)\n\n\(fallback)"
    }

    private func message(_ title: String, _ detail: String) {
        let alert = NSAlert(); alert.messageText = title; alert.informativeText = detail
        alert.addButton(withTitle: "OK"); alert.runModal()
    }
}

let arguments = CommandLine.arguments
func bundleRuntime() -> Runtime? {
    guard let resources = Bundle.main.resourceURL else { return nil }
    let root = resources.path
    return Runtime([arguments[0], root + "/runtime/FamilyActivityCore", root + "/runtime",
                    root + "/helpers/foreground", root + "/helpers/status"], frozen: true)
}
if arguments.count > 1 && arguments[1] == "--check-bundle" {
    exit(bundleRuntime() == nil ? 1 : 0)
}
if arguments.count > 1 && arguments[1] == "--check-runtime" {
    let forwarded = [arguments[0]] + arguments.dropFirst(2)
    exit(Runtime(Array(forwarded)) == nil ? 1 : 0)
}
guard let runtime = arguments.count == 1 ? bundleRuntime() : Runtime(arguments) else {
    fputs("Experimental setup requires four absolute runtime paths.\n", stderr)
    exit(2)
}
let app = NSApplication.shared
let controller = SetupController(runtime: runtime)
app.delegate = controller
app.setActivationPolicy(.regular)
app.run()
