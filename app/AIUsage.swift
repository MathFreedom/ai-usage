// AI Usage — menu bar panel showing Claude and Codex usage limits, with Codex account switching.
// Data: Claude from the usage API (Claude Code's Keychain token), falling back to
//       ~/.claude/usage-cache.json (written by claude/statusline.sh),
//       Codex from `cx json` (bin/cx). Build with ./build.sh.
import AppKit
import ServiceManagement
import SwiftUI

let home = NSHomeDirectory()
let cxPath = home + "/.local/bin/cx"
let claudeCachePath = home + "/.claude/usage-cache.json"

// MARK: - Data

struct UsageWindow: Identifiable {
    let id = UUID()
    let label: String
    let percent: Int
    let resetAt: Date?
}

struct CodexAccount: Identifiable {
    let name: String
    let email: String
    let plan: String
    let active: Bool
    let error: String?
    let limitReached: Bool
    let windows: [UsageWindow]
    let resets: [Date]  // expiry dates of available free "full reset" credits
    var id: String { name }
    var worst: UsageWindow? { windows.max { $0.percent < $1.percent } }
}

func number(_ value: Any?) -> Double? { (value as? NSNumber)?.doubleValue }

func windowLabel(seconds: Int) -> String {
    if seconds <= 6 * 3600 { return "5h" }
    if seconds >= 6 * 86400 { return "Weekly" }
    return "\(seconds / 3600)h"
}

func planName(_ plan: String) -> String {
    ["prolite": "Pro Lite", "pro": "Pro", "plus": "Plus", "team": "Team", "free": "Free"][plan] ?? plan.capitalized
}

enum Brand {
    case claude, openai
    var resource: String { self == .claude ? "claude" : "openai" }
    var fallbackSymbol: String { self == .claude ? "sparkle" : "chevron.left.forwardslash.chevron.right" }
    // Template images copied from the Claude and ChatGPT apps by build.sh, loaded once
    var image: NSImage? { self == .claude ? Brand.claudeImage : Brand.openaiImage }
    private static let claudeImage = load("claude")
    private static let openaiImage = load("openai")
    private static func load(_ name: String) -> NSImage? {
        Bundle.main.url(forResource: name, withExtension: "png").flatMap(NSImage.init(contentsOf:))
    }
}

func usageColor(_ percent: Int) -> Color { percent >= 80 ? .red : percent >= 50 ? .orange : .green }

func resetText(_ date: Date?) -> String {
    guard let date else { return "" }
    let s = max(0, Int(date.timeIntervalSinceNow))
    if s >= 86400 {
        let h = s % 86400 / 3600
        return h > 0 ? "\(s / 86400)d \(h)h" : "\(s / 86400)d"
    }
    if s >= 3600 { return "\(s / 3600)h \(s % 3600 / 60)m" }
    return "\(s / 60)m"
}

func resetDate(_ date: Date?) -> String {
    guard let date else { return "" }
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_GB")
    let cal = Calendar.current
    if cal.isDateInToday(date) { f.dateFormat = "'today' HH:mm" }
    else if cal.isDateInTomorrow(date) { f.dateFormat = "'tomorrow' HH:mm" }
    else { f.dateFormat = "EEE d MMM, HH:mm" }
    return f.string(from: date)
}

/// "Resets in 3h 26m ............ today 19:30" — remaining time, with the exact date discreetly on the right.
struct ResetLine: View {
    let prefix: String
    let date: Date?

    var body: some View {
        HStack {
            Text("\(prefix)\(resetText(date))").foregroundStyle(.secondary)
            Spacer()
            Text(resetDate(date)).foregroundStyle(.tertiary)
        }
        .font(.system(size: 10))
        .monospacedDigit()
    }
}

func runCx(_ args: [String]) -> Data {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
    process.arguments = [cxPath] + args
    let out = Pipe()
    process.standardOutput = out
    process.standardError = FileHandle.nullDevice
    do { try process.run() } catch { return Data() }
    let data = out.fileHandleForReading.readDataToEndOfFile()
    process.waitUntilExit()
    return data
}

func parseISODate(_ string: String) -> Date? {
    // Drop fractional seconds (APIs send 0 to 6 digits), then parse plain RFC 3339.
    let trimmed = string.replacingOccurrences(of: #"\.\d+"#, with: "", options: .regularExpression)
    return ISO8601DateFormatter().date(from: trimmed)
}

func shortDate(_ date: Date) -> String {
    let f = DateFormatter()
    f.locale = Locale(identifier: "en_GB")
    f.dateFormat = "d MMM"
    return f.string(from: date)
}

func parseCodex(_ data: Data) -> [CodexAccount]? {
    guard let list = (try? JSONSerialization.jsonObject(with: data)) as? [[String: Any]] else { return nil }
    return list.map { a in
        let windows = (a["windows"] as? [[String: Any]] ?? []).map { w in
            UsageWindow(
                label: windowLabel(seconds: Int(number(w["limit_window_seconds"]) ?? 0)),
                percent: Int(number(w["used_percent"]) ?? 0),
                resetAt: number(w["reset_at"]).map { Date(timeIntervalSince1970: $0) })
        }
        return CodexAccount(
            name: a["name"] as? String ?? "?",
            email: a["email"] as? String ?? "",
            plan: a["plan"] as? String ?? "",
            active: a["active"] as? Bool ?? false,
            error: a["error"] as? String,
            limitReached: a["limit_reached"] as? Bool ?? false,
            windows: windows,
            resets: (a["resets"] as? [String] ?? []).compactMap(parseISODate))
    }
}

struct ClaudeAuth {
    let token: String
    let expiresAt: Date?
    var valid: Bool { expiresAt.map { $0 > Date() } ?? true }
}

/// Claude Code's OAuth access token from the login Keychain (nil if missing or expired).
func claudeAuth() -> ClaudeAuth? {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/security")
    process.arguments = ["find-generic-password", "-s", "Claude Code-credentials", "-w"]
    let out = Pipe()
    process.standardOutput = out
    process.standardError = FileHandle.nullDevice
    do { try process.run() } catch { return nil }
    let data = out.fileHandleForReading.readDataToEndOfFile()
    process.waitUntilExit()
    guard let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
          let oauth = obj["claudeAiOauth"] as? [String: Any],
          let token = oauth["accessToken"] as? String
    else { return nil }
    let auth = ClaudeAuth(token: token, expiresAt: number(oauth["expiresAt"]).map { Date(timeIntervalSince1970: $0 / 1000) })
    return auth.valid ? auth : nil
}

/// Live Claude limits (5h, weekly, per-model weekly such as Fable) from the usage API used by Claude Code.
func fetchClaudeLive(token: String) async -> [UsageWindow]? {
    var request = URLRequest(url: URL(string: "https://api.anthropic.com/api/oauth/usage")!)
    request.timeoutInterval = 15
    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
    request.setValue("oauth-2025-04-20", forHTTPHeaderField: "anthropic-beta")
    request.setValue("ai-usage-menubar/1.0", forHTTPHeaderField: "User-Agent")
    guard let (data, response) = try? await URLSession.shared.data(for: request),
          (response as? HTTPURLResponse)?.statusCode == 200,
          let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
          let limits = obj["limits"] as? [[String: Any]]
    else { return nil }
    return limits.map { limit in
        let label: String
        switch limit["kind"] as? String {
        case "session": label = "5h"
        case "weekly_all": label = "Weekly"
        default:
            let scope = limit["scope"] as? [String: Any]
            let model = (scope?["model"] as? [String: Any])?["display_name"] as? String
            label = "\(model ?? "Other") weekly"
        }
        return UsageWindow(
            label: label,
            percent: Int(number(limit["percent"]) ?? 0),
            resetAt: (limit["resets_at"] as? String).flatMap(parseISODate))
    }
}

/// Fallback: last snapshot saved by the Claude Code status line.
func loadClaude() -> (windows: [UsageWindow], updated: Date?) {
    guard let data = FileManager.default.contents(atPath: claudeCachePath),
          let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    else { return ([], nil) }
    let limits = obj["rate_limits"] as? [String: Any] ?? [:]
    var windows: [UsageWindow] = []
    for (key, label) in [("five_hour", "5h"), ("seven_day", "Weekly")] {
        guard let w = limits[key] as? [String: Any], let pct = number(w["used_percentage"]) else { continue }
        let reset = number(w["resets_at"]).map { Date(timeIntervalSince1970: $0) }
        let elapsed = reset.map { $0 < Date() } ?? false  // window already reset since the snapshot
        windows.append(UsageWindow(label: label, percent: elapsed ? 0 : Int(pct), resetAt: elapsed ? nil : reset))
    }
    return (windows, number(obj["updated_at"]).map { Date(timeIntervalSince1970: $0) })
}

// MARK: - Model

@MainActor
final class UsageModel: ObservableObject {
    @Published var claude: [UsageWindow] = []
    @Published var claudeUpdated: Date?
    @Published var codex: [CodexAccount] = []
    @Published var codexFailed = false
    @Published var loading = false
    @Published var switching: String?
    @Published var switchNote: String?  // e.g. apps that must be restarted to follow the switch
    @Published var menuBarImage = NSImage()
    private var lastRefresh = Date.distantPast
    private var timer: Timer?
    private var auth: ClaudeAuth?  // cached until it expires or fails, to skip a `security` run per refresh
    private var menuBarItems: [MenuBarLabel.Item]?

    init() {
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 600, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.refresh() }
        }
        timer?.tolerance = 60  // lets macOS coalesce the wakeup with other activity
    }

    func refreshIfStale() {
        if Date().timeIntervalSince(lastRefresh) > 30 { refresh() }
    }

    func refresh() {
        (claude, claudeUpdated) = loadClaude()
        updateMenuBarImage()
        guard !loading else { return }
        loading = true
        lastRefresh = Date()
        Task {
            if auth?.valid != true { auth = await Task.detached { claudeAuth() }.value }
            guard let token = auth?.token else { return }
            if let live = await fetchClaudeLive(token: token) {
                self.claude = live
                self.claudeUpdated = Date()
                self.updateMenuBarImage()
            } else {
                auth = nil  // revoked or rotated by Claude Code: re-read the Keychain next time
            }
        }
        Task.detached {
            let accounts = parseCodex(runCx(["json"]))
            await MainActor.run {
                self.loading = false
                self.codexFailed = accounts == nil
                if let accounts { self.codex = accounts }
                self.updateMenuBarImage()
            }
        }
    }

    func switchTo(_ account: CodexAccount) {
        guard !account.active, switching == nil else { return }
        switching = account.name
        switchNote = nil
        Task.detached {
            let output = String(decoding: runCx(["use", account.name]), as: UTF8.self)
            let note = output.split(separator: "\n")
                .first { $0.hasPrefix("NOTE: ") }
                .map { String($0.dropFirst(6)) }
            await MainActor.run {
                self.switching = nil
                self.switchNote = note
                self.refresh()
            }
        }
    }

    func addAccount() {
        // A .command file opens in Terminal without needing Automation permission.
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("ai-usage-add-account.command")
        let script = "#!/bin/zsh\nexport PATH=\"$HOME/.local/bin:$PATH\"\ncx add\necho\nread -k 1 '?Press any key to close'\n"
        try? script.write(to: url, atomically: true, encoding: .utf8)
        try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: url.path)
        NSWorkspace.shared.open(url)
    }

    private func updateMenuBarImage() {
        var items: [MenuBarLabel.Item] = []
        if let pct = claude.map(\.percent).max() {
            items.append(.init(brand: .claude, percent: pct))
        }
        if let worst = codex.first(where: \.active)?.worst {
            items.append(.init(brand: .openai, percent: worst.percent))
        }
        guard items != menuBarItems else { return }
        menuBarItems = items
        let alert = items.contains { $0.percent >= 80 }
        let renderer = ImageRenderer(content: MenuBarLabel(items: items, color: alert ? .red : .black))
        renderer.scale = NSScreen.main?.backingScaleFactor ?? 2
        guard let image = renderer.nsImage else { return }
        image.isTemplate = !alert  // template = follows the menu bar's light/dark appearance
        menuBarImage = image
    }
}

// MARK: - Views

struct MenuBarLabel: View {
    struct Item: Equatable { let brand: Brand; let percent: Int }
    let items: [Item]
    let color: Color

    var body: some View {
        HStack(spacing: 8) {
            if items.isEmpty {
                Image(systemName: "gauge.with.needle").font(.system(size: 13, weight: .medium))
            }
            ForEach(items.indices, id: \.self) { i in
                HStack(spacing: 3) {
                    Logo(brand: items[i].brand, size: 13)
                    Text("\(items[i].percent)%").font(.system(size: 12, weight: .medium)).monospacedDigit()
                }
            }
        }
        .foregroundStyle(color)
        .padding(.vertical, 2)
    }
}

struct Logo: View {
    let brand: Brand
    let size: CGFloat

    var body: some View {
        if let image = brand.image {
            Image(nsImage: image)
                .renderingMode(.template)
                .resizable()
                .interpolation(.high)
                .frame(width: size, height: size)
        } else {
            Image(systemName: brand.fallbackSymbol).font(.system(size: size * 0.8, weight: .bold))
        }
    }
}

struct Bar: View {
    let percent: Int

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(.quaternary)
                Capsule()
                    .fill(usageColor(percent).gradient)
                    .frame(width: max(6, geo.size.width * CGFloat(min(percent, 100)) / 100))
            }
        }
        .frame(height: 6)
    }
}

struct Card<Content: View>: View {
    let title: String
    let brand: Brand
    let note: String?
    let content: Content

    init(_ title: String, brand: Brand, note: String? = nil, @ViewBuilder content: () -> Content) {
        self.title = title
        self.brand = brand
        self.note = note
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 6) {
                Logo(brand: brand, size: 15).foregroundStyle(.primary)
                Text(title).font(.system(size: 13, weight: .semibold))
                Spacer()
                if let note { Text(note).font(.system(size: 10)).foregroundStyle(.tertiary) }
            }
            content
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.quinary, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

struct UsageBar: View {
    let window: UsageWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline) {
                Text(window.label).font(.system(size: 12))
                Spacer()
                Text("\(window.percent)%").font(.system(size: 12, weight: .semibold)).monospacedDigit()
            }
            Bar(percent: window.percent)
            if window.resetAt != nil {
                ResetLine(prefix: "Resets in ", date: window.resetAt)
            }
        }
    }
}

struct AccountRow: View {
    let account: CodexAccount
    let switching: Bool
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 7) {
                HStack(spacing: 8) {
                    Image(systemName: account.active ? "checkmark.circle.fill" : "circle")
                        .font(.system(size: 14))
                        .foregroundStyle(account.active ? Color.accentColor : Color.secondary)
                    VStack(alignment: .leading, spacing: 1) {
                        Text(account.name).font(.system(size: 12, weight: .medium))
                        Text("\(account.email) · \(planName(account.plan))")
                            .font(.system(size: 10)).foregroundStyle(.secondary).lineLimit(1)
                    }
                    Spacer()
                    if switching {
                        ProgressView().controlSize(.small)
                    } else if account.limitReached {
                        Text("Limit reached").font(.system(size: 10, weight: .semibold)).foregroundStyle(.red)
                    } else if let worst = account.worst {
                        Text("\(worst.percent)%").font(.system(size: 12, weight: .semibold)).monospacedDigit()
                    }
                }
                if let error = account.error {
                    Text(error).font(.system(size: 10)).foregroundStyle(.secondary).padding(.leading, 22)
                }
                ForEach(account.windows) { w in
                    VStack(alignment: .leading, spacing: 4) {
                        Bar(percent: w.percent)
                        ResetLine(prefix: "\(w.label) · resets in ", date: w.resetAt)
                    }
                    .padding(.leading, 22)
                }
                if let first = account.resets.first {
                    HStack {
                        Label("\(account.resets.count) free reset\(account.resets.count > 1 ? "s" : "")",
                              systemImage: "arrow.counterclockwise")
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text("expires \(shortDate(first))").foregroundStyle(.tertiary)
                    }
                    .font(.system(size: 10))
                    .padding(.leading, 22)
                    .help("Expires: " + account.resets.map(resetDate).joined(separator: ", "))
                }
            }
            .padding(8)
            .contentShape(Rectangle())
            .background(
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(hover && !account.active ? Color.primary.opacity(0.07) : .clear))
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .padding(.horizontal, -8)
        .help(account.active ? "Active account" : "Switch Codex to \(account.name)")
    }
}

struct PanelView: View {
    @ObservedObject var model: UsageModel
    @State private var openAtLogin = SMAppService.mainApp.status == .enabled

    private var claudeNote: String? {
        guard let updated = model.claudeUpdated else { return nil }
        let minutes = Int(-updated.timeIntervalSinceNow / 60)
        return minutes < 1 ? "Just now" : minutes < 60 ? "\(minutes) min ago" : "\(minutes / 60) h ago"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("Usage").font(.system(size: 15, weight: .bold))
                Spacer()
                Menu {
                    Button("Codex account…", action: model.addAccount)
                } label: {
                    Image(systemName: "plus")
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)
                .fixedSize()
                .help("Add account")
                if model.loading {
                    ProgressView().controlSize(.small)
                } else {
                    Button(action: model.refresh) { Image(systemName: "arrow.clockwise") }
                        .buttonStyle(.borderless)
                        .help("Refresh")
                }
            }
            .padding(.horizontal, 2)

            Card("Claude", brand: .claude, note: claudeNote) {
                if model.claude.isEmpty {
                    Text("No data yet — open Claude Code").font(.system(size: 11)).foregroundStyle(.secondary)
                }
                ForEach(model.claude) { UsageBar(window: $0) }
            }

            Card("Codex", brand: .openai) {
                if model.codexFailed {
                    Text("Couldn't load accounts").font(.system(size: 11)).foregroundStyle(.red)
                }
                VStack(alignment: .leading, spacing: 4) {
                    ForEach(model.codex) { account in
                        AccountRow(account: account, switching: model.switching == account.name) {
                            model.switchTo(account)
                        }
                    }
                }
                if let note = model.switchNote {
                    Label(note, systemImage: "info.circle")
                        .font(.system(size: 10))
                        .foregroundStyle(.secondary)
                }
            }

            HStack {
                Toggle("Open at login", isOn: $openAtLogin)
                    .toggleStyle(.checkbox)
                    .onChange(of: openAtLogin) { _, enabled in
                        let isEnabled = SMAppService.mainApp.status == .enabled
                        guard enabled != isEnabled else { return }
                        do {
                            if enabled { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
                        } catch {
                            openAtLogin = isEnabled
                        }
                    }
                Spacer()
                Button("Quit") { NSApp.terminate(nil) }.buttonStyle(.borderless)
            }
            .font(.system(size: 11))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 2)
        }
        .padding(12)
        .frame(width: 300)
        .onReceive(NotificationCenter.default.publisher(for: NSWindow.didBecomeKeyNotification)) { _ in
            model.refreshIfStale()
        }
    }
}

// MARK: - App

@main
struct AIUsageApp: App {
    @StateObject private var model = UsageModel()

    var body: some Scene {
        MenuBarExtra {
            PanelView(model: model)
        } label: {
            Image(nsImage: model.menuBarImage)
        }
        .menuBarExtraStyle(.window)
    }
}
