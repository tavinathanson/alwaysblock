import SwiftUI
import SystemExtensions
import NetworkExtension
import os.log
import Combine

@main
struct AlwaysBlockAppApp: App {
    @StateObject private var extensionManager = ExtensionManager()
    
    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(extensionManager)
                .onAppear {
                    extensionManager.checkAndInstallExtension()
                }
        }
    }
}

class ExtensionManager: NSObject, ObservableObject, OSSystemExtensionRequestDelegate {
    @Published var isInstalled = false
    @Published var statusMessage = "Checking extension status..."
    
    private let log = Logger(subsystem: "com.tavinathanson.AlwaysBlockApp", category: "extension")
    
    func checkAndInstallExtension() {
        log.info("Checking system extension status")

        // Also try to configure the filter in case extension is already installed
        configureContentFilter()

        let request = OSSystemExtensionRequest.activationRequest(
            forExtensionWithIdentifier: "com.tavinathanson.AlwaysBlockApp.AlwaysBlockExtension",
            queue: .main
        )
        request.delegate = self
        OSSystemExtensionManager.shared.submitRequest(request)
    }
    
    // MARK: - OSSystemExtensionRequestDelegate
    
    func request(_ request: OSSystemExtensionRequest, actionForReplacingExtension existing: OSSystemExtensionProperties, withExtension ext: OSSystemExtensionProperties) -> OSSystemExtensionRequest.ReplacementAction {
        log.info("Replacing extension version \(existing.bundleShortVersion) with \(ext.bundleShortVersion)")
        return .replace
    }
    
    func requestNeedsUserApproval(_ request: OSSystemExtensionRequest) {
        log.info("Extension needs user approval")
        DispatchQueue.main.async {
            self.statusMessage = "Please allow the extension in System Settings > Privacy & Security"
        }
    }
    
    func request(_ request: OSSystemExtensionRequest, didFinishWithResult result: OSSystemExtensionRequest.Result) {
        log.info("Extension request finished with result: \(result.rawValue)")

        DispatchQueue.main.async {
            switch result {
            case .completed:
                self.isInstalled = true
                self.statusMessage = "Extension installed successfully"
                // Now configure the content filter
                self.configureContentFilter()
            case .willCompleteAfterReboot:
                self.statusMessage = "Extension will be activated after reboot"
            @unknown default:
                self.statusMessage = "Unknown result"
            }
        }
    }

    private func configureContentFilter() {
        log.info("Configuring content filter")

        // First, ensure domains are written to the shared location
        writeDomainsForExtension()

        NEFilterManager.shared().loadFromPreferences { [weak self] error in
            guard let self = self else { return }

            if let error = error {
                self.log.error("Failed to load filter preferences: \(error.localizedDescription)")
            }

            // Log current state
            self.log.info("Current filter enabled: \(NEFilterManager.shared().isEnabled)")
            self.log.info("Current provider config: \(String(describing: NEFilterManager.shared().providerConfiguration))")

            // Configure the filter with the system extension
            let configuration = NEFilterProviderConfiguration()
            configuration.filterBrowsers = true
            configuration.filterSockets = true

            // For system extensions, we need to specify the bundle ID in organization and username
            configuration.organization = "AlwaysBlock"
            configuration.username = "system"
            configuration.serverAddress = "com.tavinathanson.AlwaysBlockApp.AlwaysBlockExtension"

            NEFilterManager.shared().providerConfiguration = configuration
            NEFilterManager.shared().isEnabled = true
            NEFilterManager.shared().localizedDescription = "AlwaysBlock Content Filter"

            self.log.info("About to save config - filterBrowsers: \(configuration.filterBrowsers), filterSockets: \(configuration.filterSockets)")

            // Save the configuration
            NEFilterManager.shared().saveToPreferences { [weak self] error in
                if let error = error {
                    self?.log.error("Failed to save filter preferences: \(error.localizedDescription)")
                    DispatchQueue.main.async {
                        self?.statusMessage = "Failed to configure filter: \(error.localizedDescription)"
                    }
                } else {
                    self?.log.info("✅ Content filter configured and enabled successfully")

                    // Verify it saved
                    NEFilterManager.shared().loadFromPreferences { error in
                        if let error = error {
                            self?.log.error("Verification load failed: \(error.localizedDescription)")
                        } else {
                            self?.log.info("Verification - isEnabled: \(NEFilterManager.shared().isEnabled)")
                            self?.log.info("Verification - config: \(String(describing: NEFilterManager.shared().providerConfiguration))")
                        }
                    }

                    DispatchQueue.main.async {
                        self?.statusMessage = "Content filter active"
                    }
                }
            }
        }
    }

    private func writeDomainsForExtension() {
        log.info("Writing domains for extension")

        // Call the Python CLI to generate the domains JSON
        // This ensures we use the exact same logic as the CLI
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/local/bin/alwaysblock")
        task.arguments = ["status"]

        do {
            try task.run()
            task.waitUntilExit()
            log.info("Domains written to /tmp/alwaysblock_domains.json")
        } catch {
            log.error("Failed to run alwaysblock CLI: \(error.localizedDescription)")
        }
    }
    
    func request(_ request: OSSystemExtensionRequest, didFailWithError error: Error) {
        log.error("Extension request failed: \(error.localizedDescription)")
        DispatchQueue.main.async {
            self.statusMessage = "Failed to install extension: \(error.localizedDescription)"
        }
    }
}
