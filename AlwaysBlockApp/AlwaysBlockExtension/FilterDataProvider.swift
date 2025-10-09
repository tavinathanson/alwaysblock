import NetworkExtension
import os.log

class FilterDataProvider: NEFilterDataProvider {
    
    private let log = Logger(subsystem: "com.tavinathanson.AlwaysBlockApp.AlwaysBlockExtension", category: "filter")
    private var blockedDomains: Set<String> = []
    private var domainExpirations: [String: Date] = [:]
    private let storageURL: URL
    
    override init() {
        // Store blocked domains in app's documents directory
        let documentsPath = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        self.storageURL = documentsPath.appendingPathComponent("alwaysblock_domains.json")
        
        super.init()
        loadBlockedDomains()
    }
    
    override func startFilter(completionHandler: @escaping (Error?) -> Void) {
        log.info("Starting AlwaysBlock content filter")
        loadBlockedDomains()
        
        // Set up file watcher for domain updates
        startFileWatcher()
        
        completionHandler(nil)
    }
    
    override func stopFilter(with reason: NEProviderStopReason, completionHandler: @escaping () -> Void) {
        log.info("Stopping content filter: \(reason.rawValue)")
        completionHandler()
    }
    
    override func handleNewFlow(_ flow: NEFilterFlow) -> NEFilterNewFlowVerdict {
        guard let socketFlow = flow as? NEFilterSocketFlow else {
            return .allow()
        }
        
        // Get hostname from the remote endpoint
        guard let hostname = socketFlow.remoteHostname else {
            // No hostname available (likely an IP address), allow the connection
            return .allow()
        }
        
        // Clean expired domains
        cleanExpiredDomains()
        
        // Check if domain should be blocked
        if shouldBlockDomain(hostname) {
            log.info("Blocking flow to: \(hostname)")
            return .drop()
        }
        
        return .allow()
    }
    
    // MARK: - Domain Management
    
    private func shouldBlockDomain(_ hostname: String) -> Bool {
        // Direct match
        if self.blockedDomains.contains(hostname) {
            return true
        }
        
        // Check without www
        if hostname.hasPrefix("www.") {
            let withoutWWW = String(hostname.dropFirst(4))
            if self.blockedDomains.contains(withoutWWW) {
                return true
            }
        }
        
        // Check subdomains
        let components = hostname.components(separatedBy: ".")
        for i in 0..<components.count {
            let domain = components[i...].joined(separator: ".")
            if self.blockedDomains.contains(domain) {
                return true
            }
        }
        
        return false
    }
    
    private func cleanExpiredDomains() {
        let now = Date()
        var domainsToRemove: [String] = []
        
        for (domain, expiration) in domainExpirations {
            if expiration < now {
                domainsToRemove.append(domain)
            }
        }
        
        for domain in domainsToRemove {
            blockedDomains.remove(domain)
            domainExpirations.removeValue(forKey: domain)
            log.info("Domain expired: \(domain)")
        }
        
        if !domainsToRemove.isEmpty {
            saveBlockedDomains()
        }
    }
    
    // MARK: - Persistence
    
    private func loadBlockedDomains() {
        guard FileManager.default.fileExists(atPath: storageURL.path) else {
            log.info("No blocked domains file found")
            return
        }
        
        do {
            let data = try Data(contentsOf: storageURL)
            let decoded = try JSONDecoder().decode(BlockedDomainsStorage.self, from: data)
            self.blockedDomains = Set(decoded.domains)
            self.domainExpirations = decoded.expirations.compactMapValues { Date(timeIntervalSince1970: $0) }
            
            log.info("Loaded \(self.blockedDomains.count) blocked domains")
        } catch {
            log.error("Failed to load blocked domains: \(error.localizedDescription)")
        }
    }
    
    private func saveBlockedDomains() {
        let storage = BlockedDomainsStorage(
            domains: Array(blockedDomains),
            expirations: domainExpirations.mapValues { $0.timeIntervalSince1970 }
        )
        
        do {
            let data = try JSONEncoder().encode(storage)
            try data.write(to: storageURL)
            log.info("Saved \(self.blockedDomains.count) blocked domains")
        } catch {
            log.error("Failed to save blocked domains: \(error.localizedDescription)")
        }
    }
    
    // MARK: - File Watching
    
    private func startFileWatcher() {
        // Monitor the storage file for changes from the CLI
        let queue = DispatchQueue(label: "com.alwaysblock.filewatcher")
        
        queue.async { [weak self] in
            while true {
                Thread.sleep(forTimeInterval: 1.0) // Check every second
                self?.loadBlockedDomains()
            }
        }
    }
}

// MARK: - Supporting Types

struct BlockedDomainsStorage: Codable {
    let domains: [String]
    let expirations: [String: TimeInterval]
}
