import SwiftUI
import SystemExtensions
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
            case .willCompleteAfterReboot:
                self.statusMessage = "Extension will be activated after reboot"
            @unknown default:
                self.statusMessage = "Unknown result"
            }
        }
    }
    
    func request(_ request: OSSystemExtensionRequest, didFailWithError error: Error) {
        log.error("Extension request failed: \(error.localizedDescription)")
        DispatchQueue.main.async {
            self.statusMessage = "Failed to install extension: \(error.localizedDescription)"
        }
    }
}
