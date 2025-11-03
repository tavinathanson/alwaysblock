import NetworkExtension
import os.log

class FilterDataProvider: NEFilterDataProvider {
    
    private let log = Logger(subsystem: "com.tavinathanson.AlwaysBlockApp.AlwaysBlockExtension", category: "filter")
    private var blockedDomains: Set<String> = []
    private var domainExpirations: [String: Date] = [:]
    private let storageURL: URL
    
    override init() {
        // Use a shared location accessible without App Groups (for local signing)
        // Both CLI and extension can access /tmp
        self.storageURL = URL(fileURLWithPath: "/tmp/alwaysblock_domains.json")

        super.init()

        log.error("📁 FilterDataProvider init - storage URL: \(self.storageURL.path)")
        log.error("📁 File exists: \(FileManager.default.fileExists(atPath: self.storageURL.path))")

        loadBlockedDomains()
    }
    
    override func startFilter(completionHandler: @escaping (Error?) -> Void) {
        log.info("Starting AlwaysBlock content filter")
        loadBlockedDomains()

        // Set up file watcher for domain updates
        startFileWatcher()

        log.info("Filter started with \(self.blockedDomains.count) blocked domains")

        completionHandler(nil)
    }
    
    override func stopFilter(with reason: NEProviderStopReason, completionHandler: @escaping () -> Void) {
        log.info("Stopping content filter: \(reason.rawValue)")
        completionHandler()
    }
    
    override func handleNewFlow(_ flow: NEFilterFlow) -> NEFilterNewFlowVerdict {
        // On macOS, we only get NEFilterSocketFlow
        guard let socketFlow = flow as? NEFilterSocketFlow else {
            return .allow()
        }

        // Get hostname from the remote endpoint
        if let hostname = socketFlow.remoteHostname {
            // Clean expired domains
            cleanExpiredDomains()

            // Check if domain should be blocked
            if shouldBlockDomain(hostname) {
                log.info("Blocking flow to: \(hostname, privacy: .public)")
                return .drop()
            }

            return .allow()
        } else {
            // For flows without hostname (like Chrome's direct IP connections),
            // we need to peek at the data to extract the SNI hostname
            // On macOS, we use filterDataVerdict to inspect outbound data
            let peekBytes = 512 // Enough to capture TLS ClientHello SNI
            return NEFilterNewFlowVerdict.filterDataVerdict(
                withFilterInbound: false,
                peekInboundBytes: 0,
                filterOutbound: true,
                peekOutboundBytes: peekBytes
            )
        }
    }

    override func handleOutboundData(from flow: NEFilterFlow, readBytesStartOffset offset: Int, readBytes: Data) -> NEFilterDataVerdict {
        // Try to extract SNI hostname from TLS ClientHello
        if let hostname = extractSNIHostname(from: readBytes) {
            if shouldBlockDomain(hostname) {
                log.info("Blocking flow to SNI: \(hostname, privacy: .public)")
                return .drop()
            }
        }

        // Allow the data through
        return .allow()
    }

    private func extractSNIHostname(from data: Data) -> String? {
        // TLS ClientHello SNI extraction
        // Reference: RFC 6066 Section 3 (Server Name Indication)

        guard data.count > 43 else { return nil }

        // Check if this looks like a TLS ClientHello (0x16 = handshake, 0x03 = SSL/TLS)
        guard data[0] == 0x16, data[1] == 0x03 else { return nil }

        // Skip: record header (5) + handshake type (1) + handshake length (3) +
        //       client version (2) + random (32) + session ID length (1)
        var pos = 5 + 1 + 3 + 2 + 32
        guard pos < data.count else { return nil }

        // Skip session ID
        let sessionIdLength = Int(data[pos])
        pos += 1 + sessionIdLength
        guard pos + 2 < data.count else { return nil }

        // Skip cipher suites
        let cipherSuitesLength = Int(UInt16(data[pos]) << 8 | UInt16(data[pos + 1]))
        pos += 2 + cipherSuitesLength
        guard pos + 1 < data.count else { return nil }

        // Skip compression methods
        let compressionMethodsLength = Int(data[pos])
        pos += 1 + compressionMethodsLength
        guard pos + 2 < data.count else { return nil }

        // Now we're at extensions
        let extensionsLength = Int(UInt16(data[pos]) << 8 | UInt16(data[pos + 1]))
        pos += 2
        let extensionsEnd = pos + extensionsLength

        // Search for SNI extension (type 0x0000)
        while pos + 4 <= extensionsEnd && pos + 4 < data.count {
            let extensionType = UInt16(data[pos]) << 8 | UInt16(data[pos + 1])
            let extensionLength = Int(UInt16(data[pos + 2]) << 8 | UInt16(data[pos + 3]))

            if extensionType == 0x0000 { // SNI extension
                // SNI format: list length (2), type (1), name length (2), name
                guard pos + 9 < data.count else { return nil }

                let nameLength = Int(UInt16(data[pos + 7]) << 8 | UInt16(data[pos + 8]))
                guard pos + 9 + nameLength <= data.count else { return nil }

                let hostnameData = data.subdata(in: (pos + 9)..<(pos + 9 + nameLength))
                return String(data: hostnameData, encoding: .ascii)
            }

            pos += 4 + extensionLength
        }

        return nil
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
