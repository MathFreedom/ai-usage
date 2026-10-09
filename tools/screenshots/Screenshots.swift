// Renders the README screenshots from the app's real SwiftUI views, fed with fictional data,
// on a reconstructed macOS desktop (wallpaper + menu bar). Run ./render.sh.
import AppKit
import SwiftUI

// MARK: - Fictional data

func hours(_ h: Double) -> Date { Date().addingTimeInterval(h * 3600) }

func window(_ label: String, _ percent: Int, resetsIn h: Double) -> UsageWindow {
    UsageWindow(label: label, percent: percent, resetAt: hours(h))
}

@MainActor
/// `singleClaude`: one saved Claude account, so the card shows plain limit bars instead of rows.
func demoModel(singleClaude: Bool) -> UsageModel {
    let model = UsageModel(live: false)
    let personal = Account(
        brand: .claude, name: "personal", email: "alex@example.com", plan: "max", active: true,
        error: nil, limitReached: false,
        windows: [window("5h", 34, resetsIn: 2.2), window("Weekly", 62, resetsIn: 98)],
        resets: [], lastSeen: nil)
    let work = Account(
        brand: .claude, name: "work", email: "alex@acme.example", plan: "pro", active: false,
        error: nil, limitReached: false,
        windows: [window("5h", 0, resetsIn: 3.5), window("Weekly", 27, resetsIn: 40)],
        resets: [], lastSeen: hours(-5))
    model.claudeAccounts = singleClaude ? [personal] : [personal, work]
    model.claude = personal.windows
    model.claudeUpdated = Date()
    model.codex = [
        Account(brand: .openai, name: "personal", email: "alex@example.com", plan: "pro", active: true,
                error: nil, limitReached: false, windows: [window("Weekly", 18, resetsIn: 116)],
                resets: [hours(24 * 13), hours(24 * 20)], lastSeen: nil),
        Account(brand: .openai, name: "side-project", email: "alex@side.example", plan: "prolite", active: false,
                error: nil, limitReached: false, windows: [window("Weekly", 86, resetsIn: 30)],
                resets: [], lastSeen: nil),
    ]
    return model
}

// MARK: - Reconstructed desktop

/// Apple-style fluid wallpaper: a 4×4 mesh gradient in blues, with slightly offset control
/// points so the color fields melt into each other organically.
struct Wallpaper: View {
    let dark: Bool

    private static let points: [SIMD2<Float>] = [
        [0.00, 0.00], [0.33, 0.00], [0.67, 0.00], [1.00, 0.00],
        [0.00, 0.30], [0.42, 0.22], [0.70, 0.38], [1.00, 0.33],
        [0.00, 0.68], [0.25, 0.70], [0.62, 0.62], [1.00, 0.70],
        [0.00, 1.00], [0.36, 1.00], [0.70, 1.00], [1.00, 1.00],
    ]

    private static func rgb(_ r: Double, _ g: Double, _ b: Double) -> Color {
        Color(red: r / 255, green: g / 255, blue: b / 255)
    }

    private static let light: [Color] = [
        rgb(122, 162, 247), rgb(150, 178, 250), rgb(186, 196, 252), rgb(206, 200, 250),
        rgb(104, 150, 240), rgb(232, 238, 255), rgb(170, 190, 252), rgb(196, 186, 246),
        rgb(132, 190, 246), rgb(150, 182, 250), rgb(112, 140, 236), rgb(160, 160, 240),
        rgb(176, 214, 250), rgb(140, 176, 246), rgb(96, 124, 226), rgb(120, 130, 228),
    ]

    private static let dark: [Color] = [
        rgb(34, 52, 120), rgb(46, 70, 160), rgb(64, 74, 178), rgb(54, 50, 140),
        rgb(40, 76, 176), rgb(92, 140, 236), rgb(70, 96, 210), rgb(62, 56, 156),
        rgb(36, 92, 184), rgb(64, 112, 222), rgb(98, 112, 240), rgb(52, 64, 168),
        rgb(28, 54, 124), rgb(42, 84, 180), rgb(68, 92, 208), rgb(34, 40, 112),
    ]

    var body: some View {
        MeshGradient(width: 4, height: 4, points: Self.points, colors: dark ? Self.dark : Self.light,
                     smoothsColors: true)
    }
}

struct MenuBar: View {
    let dark: Bool
    let label: NSImage

    private var clock: String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_GB")
        f.dateFormat = "EEE d MMM  HH:mm"
        return f.string(from: Date())
    }

    var body: some View {
        HStack(spacing: 18) {
            Spacer()
            Image(nsImage: label)
            Image(systemName: "wifi")
            Image(systemName: "battery.75percent")
            Image(systemName: "magnifyingglass")
            Image(systemName: "switch.2")
            Text(clock).monospacedDigit()
        }
        .font(.system(size: 13, weight: .medium))
        .foregroundStyle(dark ? Color.white : Color.black)
        .padding(.horizontal, 18)
        .frame(height: 30)
        .background(dark ? Color.black.opacity(0.28) : Color.white.opacity(0.35))
    }
}

/// The panel as macOS draws a menu bar extra window: rounded, translucent, hairline border, soft shadow.
struct PanelChrome: View {
    let model: UsageModel
    let dark: Bool

    var body: some View {
        PanelView(model: model)
            .background(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .fill(dark ? Color(white: 0.13).opacity(0.94) : Color(white: 0.97).opacity(0.94)))
            .overlay(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .strokeBorder(dark ? Color.white.opacity(0.12) : Color.black.opacity(0.08), lineWidth: 1))
            .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))
            .shadow(color: .black.opacity(dark ? 0.55 : 0.22), radius: 30, y: 14)
    }
}

struct Desktop: View {
    let model: UsageModel
    let dark: Bool
    let label: NSImage

    /// The image is as tall as the panel needs, plus a margin: no empty wallpaper below it.
    var body: some View {
        VStack(spacing: 0) {
            MenuBar(dark: dark, label: label)
            HStack {
                Spacer()
                PanelChrome(model: model, dark: dark)
                    .padding(.trailing, 262)
                    .padding(.top, 8)
            }
        }
        .padding(.bottom, 64)
        .frame(width: 780)
        .background(Wallpaper(dark: dark))
    }
}

// MARK: - Rendering

@MainActor
func menuBarLabel(dark: Bool) -> NSImage {
    let items: [MenuBarLabel.Item] = [.init(brand: .claude, percent: 62), .init(brand: .openai, percent: 18)]
    let renderer = ImageRenderer(content: MenuBarLabel(items: items, neutral: dark ? .white : .black, colored: true))
    renderer.scale = 2
    return renderer.nsImage ?? NSImage()
}

/// Draws a view in an offscreen window (so AppKit-backed controls render too) and saves a PNG.
@MainActor
func render<V: View>(_ view: V, appearance: NSAppearance.Name, to path: String) throws {
    let host = NSHostingView(rootView: view)
    host.appearance = NSAppearance(named: appearance)
    host.frame = CGRect(origin: .zero, size: host.fittingSize)
    let window = NSWindow(contentRect: host.frame, styleMask: .borderless, backing: .buffered, defer: false)
    window.appearance = NSAppearance(named: appearance)
    window.backgroundColor = .clear
    window.isOpaque = false
    window.contentView = host
    window.setFrameOrigin(CGPoint(x: -20000, y: -20000))
    window.orderFrontRegardless()
    host.layoutSubtreeIfNeeded()
    RunLoop.main.run(until: Date().addingTimeInterval(0.5))
    guard let rep = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { return }
    host.cacheDisplay(in: host.bounds, to: rep)
    window.orderOut(nil)
    try rep.representation(using: .png, properties: [:])?.write(to: URL(fileURLWithPath: path))
    print("wrote \(path) (\(rep.pixelsWide)×\(rep.pixelsHigh))")
}

@main
struct Screenshots {
    @MainActor
    static func main() throws {
        UserDefaults.standard.register(defaults: [Language.key: Language.english.rawValue])  // README is in English
        let app = NSApplication.shared
        app.setActivationPolicy(.prohibited)
        let out = CommandLine.arguments.dropFirst().first ?? "."
        for (dark, suffix) in [(true, "dark"), (false, "light")] {
            let model = demoModel(singleClaude: dark)  // one look at each Claude card layout
            let appearance: NSAppearance.Name = dark ? .darkAqua : .aqua
            try render(Desktop(model: model, dark: dark, label: menuBarLabel(dark: dark)),
                       appearance: appearance, to: "\(out)/desktop-\(suffix).png")
        }
    }
}
