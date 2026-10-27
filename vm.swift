import AppKit
import Foundation
import Virtualization

let shared = URL(fileURLWithPath: "/Volumes/porter-crush/home/shared").resolvingSymlinksInPath()
let imageURL = shared.appendingPathComponent("UniversalMac_26.0_25A353_Restore.ipsw")
let guest = shared.appendingPathComponent("xnu-lab-macos-26")
let diskBytes: UInt64 = 64 * 1024 * 1024 * 1024
let memoryBytes: UInt64 = 4 * 1024 * 1024 * 1024

func log(_ text: String) {
    print("\(ISO8601DateFormatter().string(from: Date())) \(text)")
    fflush(stdout)
}

func failure(_ message: String) -> NSError {
    NSError(domain: "xnu-lab", code: 1,
            userInfo: [NSLocalizedDescriptionKey: message])
}

@MainActor
func configuration(_ platform: VZMacPlatformConfiguration) throws -> VZVirtualMachineConfiguration {
    let config = VZVirtualMachineConfiguration()
    config.platform = platform
    config.bootLoader = VZMacOSBootLoader()
    config.cpuCount = 2
    config.memorySize = memoryBytes
    let graphics = VZMacGraphicsDeviceConfiguration()
    graphics.displays = [VZMacGraphicsDisplayConfiguration(widthInPixels: 1440,
                          heightInPixels: 900, pixelsPerInch: 110)]
    config.graphicsDevices = [graphics]
    config.keyboards = [VZUSBKeyboardConfiguration()]
    config.pointingDevices = [VZUSBScreenCoordinatePointingDeviceConfiguration()]
    config.entropyDevices = [VZVirtioEntropyDeviceConfiguration()]
    let network = VZVirtioNetworkDeviceConfiguration()
    network.attachment = VZNATNetworkDeviceAttachment()
    config.networkDevices = [network]
    let attachment = try VZDiskImageStorageDeviceAttachment(
        url: guest.appendingPathComponent("disk.img"), readOnly: false)
    config.storageDevices = [VZVirtioBlockDeviceConfiguration(attachment: attachment)]
    try config.validate()
    return config
}

@MainActor
func existingPlatform() throws -> VZMacPlatformConfiguration {
    let modelData = try Data(contentsOf: guest.appendingPathComponent("hardware-model"))
    let identifierData = try Data(contentsOf: guest.appendingPathComponent("machine-id"))
    guard let model = VZMacHardwareModel(dataRepresentation: modelData),
          model.isSupported,
          let identifier = VZMacMachineIdentifier(dataRepresentation: identifierData) else {
        throw failure("Saved machine identity is unsupported")
    }
    let platform = VZMacPlatformConfiguration()
    platform.hardwareModel = model
    platform.machineIdentifier = identifier
    platform.auxiliaryStorage = VZMacAuxiliaryStorage(url: guest.appendingPathComponent("auxiliary"))
    return platform
}

@MainActor
final class Controller: NSObject, NSApplicationDelegate, @preconcurrency VZVirtualMachineDelegate {
    var machine: VZVirtualMachine?
    var installer: VZMacOSInstaller?
    var window: NSWindow?
    var timer: Timer?
    let action: String

    init(action: String) {
        self.action = action
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        Task { @MainActor in
            do {
                try await perform()
            } catch {
                log("error=\(error as NSError) details=\((error as NSError).userInfo)")
                exit(1)
            }
        }
    }

    func perform() async throws {
        if action == "inspect" || action == "install" || action == "retry-install" {
            log("loading_restore_image=\(imageURL.path)")
            let image = try await VZMacOSRestoreImage.image(from: imageURL)
            log("restore_build=\(image.buildVersion) restore_version=\(image.operatingSystemVersion)")
            guard let requirements = image.mostFeaturefulSupportedConfiguration else {
                throw failure("Restore image has no supported configuration on this host")
            }
            log("minimum_cpus=\(requirements.minimumSupportedCPUCount) minimum_memory=\(requirements.minimumSupportedMemorySize)")
            if action == "inspect" {
                exit(0)
            }
            if action == "retry-install" {
                guard !FileManager.default.fileExists(atPath: guest.appendingPathComponent("installed").path) else {
                    throw failure("Refusing to reinstall a completed guest")
                }
                let vm = VZVirtualMachine(configuration: try configuration(existingPlatform()))
                machine = vm
                let restore = VZMacOSInstaller(virtualMachine: vm, restoringFromImageAt: imageURL)
                installer = restore
                log("retry_install_started")
                try await restore.install()
                try Data("installed\n".utf8).write(to: guest.appendingPathComponent("installed"))
                log("install_complete")
                exit(0)
            }
            guard !FileManager.default.fileExists(atPath: guest.path) else {
                throw failure("Guest directory already exists; refusing to overwrite or reinstall")
            }
            guard requirements.minimumSupportedCPUCount <= 2,
                  requirements.minimumSupportedMemorySize <= memoryBytes else {
                throw failure("Restore image exceeds configured resource budget")
            }
            try FileManager.default.createDirectory(at: guest, withIntermediateDirectories: false)
            let disk = guest.appendingPathComponent("disk.img")
            guard FileManager.default.createFile(atPath: disk.path, contents: nil) else {
                throw failure("Cannot create guest disk")
            }
            let file = try FileHandle(forWritingTo: disk)
            try file.truncate(atOffset: diskBytes)
            try file.close()
            let platform = VZMacPlatformConfiguration()
            platform.hardwareModel = requirements.hardwareModel
            platform.machineIdentifier = VZMacMachineIdentifier()
            try platform.hardwareModel.dataRepresentation.write(to: guest.appendingPathComponent("hardware-model"))
            try platform.machineIdentifier.dataRepresentation.write(to: guest.appendingPathComponent("machine-id"))
            platform.auxiliaryStorage = try VZMacAuxiliaryStorage(
                creatingStorageAt: guest.appendingPathComponent("auxiliary"),
                hardwareModel: platform.hardwareModel)
            let vm = VZVirtualMachine(configuration: try configuration(platform))
            machine = vm
            let restore = VZMacOSInstaller(virtualMachine: vm, restoringFromImageAt: imageURL)
            installer = restore
            timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
                MainActor.assumeIsolated {
                    if let progress = self?.installer?.progress {
                        log("install_progress=\(progress.fractionCompleted)")
                    }
                }
            }
            log("install_started cpus=2 memory_bytes=\(memoryBytes) disk_bytes=\(diskBytes)")
            try await restore.install()
            timer?.invalidate()
            try Data("installed\n".utf8).write(to: guest.appendingPathComponent("installed"))
            log("install_complete guest=\(guest.path)")
            exit(0)
        }
        guard FileManager.default.fileExists(atPath: guest.appendingPathComponent("installed").path) else {
            throw failure("No completed guest installation")
        }
        let vm = VZVirtualMachine(configuration: try configuration(existingPlatform()))
        machine = vm
        vm.delegate = self
        let view = VZVirtualMachineView()
        view.virtualMachine = vm
        view.capturesSystemKeys = true
        let display = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1100, height: 750),
                               styleMask: [.titled, .closable, .resizable, .miniaturizable],
                               backing: .buffered, defer: false)
        display.title = "XNU lab: macOS 26 (\(action))"
        display.contentView = view
        display.center()
        display.makeKeyAndOrderFront(nil)
        window = display
        NSApplication.shared.activate(ignoringOtherApps: true)
        let options = VZMacOSVirtualMachineStartOptions()
        options.startUpFromMacOSRecovery = action == "recovery"
        try await vm.start(options: options)
        log("guest_started mode=\(action)")
    }

    func guestDidStop(_ virtualMachine: VZVirtualMachine) {
        log("guest_stopped")
        NSApplication.shared.terminate(nil)
    }

    func virtualMachine(_ virtualMachine: VZVirtualMachine, didStopWithError error: Error) {
        log("guest_error=\(error.localizedDescription)")
        exit(1)
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }
}

let arguments = CommandLine.arguments
let supported = ["inspect", "install", "retry-install", "run", "recovery"]
guard arguments.count == 2, supported.contains(arguments[1]) else {
    print("usage: xnu-vm inspect|install|retry-install|run|recovery")
    exit(2)
}
MainActor.assumeIsolated {
    let application = NSApplication.shared
    let controller = Controller(action: arguments[1])
    application.delegate = controller
    application.setActivationPolicy(arguments[1] == "run" || arguments[1] == "recovery" ? .regular : .accessory)
    withExtendedLifetime(controller) {
        application.run()
    }
}
