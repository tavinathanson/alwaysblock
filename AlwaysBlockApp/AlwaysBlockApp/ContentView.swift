import SwiftUI

struct ContentView: View {
    @EnvironmentObject var extensionManager: ExtensionManager
    
    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: extensionManager.isInstalled ? "checkmark.shield.fill" : "shield.slash")
                .imageScale(.large)
                .foregroundStyle(extensionManager.isInstalled ? .green : .orange)
                .font(.system(size: 60))
            
            Text("AlwaysBlock")
                .font(.largeTitle)
                .fontWeight(.bold)
            
            Text(extensionManager.statusMessage)
                .font(.headline)
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
            
            if extensionManager.isInstalled {
                VStack(spacing: 10) {
                    Text("Extension is active!")
                        .font(.headline)
                        .foregroundStyle(.green)
                    
                    Text("Use the 'alwaysblock' command in Terminal to manage blocked sites.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                }
                .padding(.top)
            }
        }
        .padding(40)
        .frame(minWidth: 400, minHeight: 300)
    }
}

#Preview {
    ContentView()
        .environmentObject(ExtensionManager())
}
