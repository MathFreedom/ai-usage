// AI Usage — menu bar panel showing Claude and Codex usage limits, with account switching for both.
// Data: Claude accounts from `ccx json` (bin/ccx); with no active saved account, the usage API
//       (Claude Code's Keychain token), falling back to the last Claude usage the app read.
//       Codex accounts from `cx json` (bin/cx). Build with ./build.sh.
import AppKit
import ServiceManagement
import SwiftUI

let home = NSHomeDirectory()
let cxPath = home + "/.local/bin/cx"
let ccxPath = home + "/.local/bin/ccx"

// MARK: - Data

struct UsageWindow: Identifiable {
    let id = UUID()
    let label: String
    let percent: Int
    let resetAt: Date?
}

struct Account: Identifiable {
    let brand: Brand
    let name: String
    let email: String
    let plan: String
    let active: Bool
    let error: String?
    let limitReached: Bool
    let windows: [UsageWindow]
    let resets: [Date]  // expiry dates of available free "full reset" credits (Codex)
    let lastSeen: Date?  // set when usage is the last known one (inactive Claude account, expired token, usage API unreachable)
    var id: String { name }
    var key: String { "\(brand.resource):\(name)" }
    var worst: UsageWindow? { windows.max { $0.percent < $1.percent } }
}

func number(_ value: Any?) -> Double? { (value as? NSNumber)?.doubleValue }

func windowLabel(seconds: Int) -> String {
    if seconds <= 6 * 3600 { return "5h" }
    if seconds >= 6 * 86400 { return "Weekly" }
    return "\(seconds / 3600)h"
}

/// The limit the menu bar shows: the one labeled `choice`, else (no choice, or not on this
/// account) the most used one, as before the setting existed.
func menuBarWindow(_ windows: [UsageWindow], choice: String) -> UsageWindow? {
    let chosen = choice.isEmpty ? [] : windows.filter { $0.label == choice }
    return (chosen.isEmpty ? windows : chosen).max { $0.percent < $1.percent }
}

/// The labels offered in the settings: this account's limits, plus the saved choice when the
/// account doesn't have it (the menu then still shows what is selected).
func menuBarChoices(_ windows: [UsageWindow], saved: String) -> [String] {
    var labels: [String] = []
    for w in windows where !labels.contains(w.label) { labels.append(w.label) }
    if !saved.isEmpty && !labels.contains(saved) { labels.append(saved) }
    return labels
}

func planName(_ plan: String) -> String {
    if plan == "free" { return tr("Free", "Gratuit") }
    return ["prolite": "Pro Lite", "pro": "Pro", "plus": "Plus", "team": "Team", "max": "Max"][plan] ?? plan.capitalized
}

enum Brand {
    case claude, openai
    var resource: String { self == .claude ? "claude" : "openai" }
    var product: String { self == .claude ? "Claude Code" : "Codex" }
    var tool: String { self == .claude ? ccxPath : cxPath }
    var fallbackSymbol: String { self == .claude ? "sparkle" : "chevron.left.forwardslash.chevron.right" }
    /// Setting: the limit label the menu bar shows ("5h", "Weekly", "Fable weekly"…), empty for the most used.
    var menuBarChoiceKey: String { self == .claude ? "menuBarClaude" : "menuBarCodex" }
    // Template images copied from the Claude and ChatGPT apps by build.sh, loaded once
    var image: NSImage? { self == .claude ? Brand.claudeImage : Brand.openaiImage }
    private static let claudeImage = load("claude")
    private static let openaiImage = load("openai")
    private static func load(_ name: String) -> NSImage? {
        Bundle.main.url(forResource: name, withExtension: "png").flatMap(NSImage.init(contentsOf:))
    }
}

// MARK: - Language

enum Language: String, CaseIterable, Identifiable {
    case english = "en", french = "fr"
    static let key = "language"

    /// The saved choice, else English.
    static var current: Language {
        if let raw = UserDefaults.standard.string(forKey: key), let saved = Language(rawValue: raw) { return saved }
        return .english
    }

    var id: String { rawValue }
    var name: String { self == .english ? "English" : "Français" }
    var locale: Locale { Locale(identifier: self == .english ? "en_GB" : "fr_FR") }
}

enum Theme: String, CaseIterable, Identifiable {
    case system, light, dark
    static let key = "theme"

    var id: String { rawValue }
    var name: String {
        switch self {
        case .system: tr("Automatic", "Automatique")
        case .light: tr("Light", "Clair")
        case .dark: tr("Dark", "Sombre")
        }
    }
    /// nil follows the system appearance.
    var appearance: NSAppearance? {
        switch self {
        case .system: nil
        case .light: NSAppearance(named: .aqua)
        case .dark: NSAppearance(named: .darkAqua)
        }
    }
}

/// The string for the current language.
func tr(_ en: String, _ fr: String) -> String { Language.current == .french ? fr : en }

/// Limit names come from the APIs in English ("5h", "Weekly", "Fable weekly").
func windowName(_ label: String) -> String {
    guard Language.current == .french else { return label }
    if label == "Weekly" { return "Semaine" }
    if label.hasSuffix(" weekly") { return label.dropLast(7) + " · semaine" }
    return label
}

/// Messages printed in English by cx/ccx (or by the app), shown in the current language.
func localized(_ message: String) -> String {
    guard Language.current == .french else { return message }
    let patterns: [(String, String)] = [
        (#"^Restart open Claude Code sessions \((\d+) running\) to use this account\.$"#,
         "Relancez les sessions Claude Code ouvertes ($1) pour utiliser ce compte."),
        (#"^Restart (.+) to use this account there\.$"#, "Relancez $1 pour y utiliser ce compte."),
        (#"^The Codex daemon is still running on the previous account: run codex app-server daemon restart in a terminal\.$"#,
         "Le daemon Codex tourne encore sur le compte précédent : lancez codex app-server daemon restart dans un terminal."),
        (#"^An open Claude Code session switched back to (.+)\. Close it, then switch again\.$"#,
         "Une session Claude Code ouverte est revenue à $1. Fermez-la, puis basculez à nouveau."),
        (#"^token expired \(cx use refreshes it\)$"#, "jeton expiré (cx use le renouvelle)"),
        (#"^credentials missing$"#, "identifiants introuvables"),
        (#"^usage unreachable$"#, "usage injoignable"),
        (#"^API key sign-in: no plan usage$"#, "connexion par clé API : pas d’usage d’abonnement"),
    ]
    for (pattern, template) in patterns {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { continue }
        let range = NSRange(message.startIndex..., in: message)
        if regex.firstMatch(in: message, range: range) != nil {
            return regex.stringByReplacingMatches(in: message, range: range, withTemplate: template)
                .replacingOccurrences(of: " and ", with: " et ")
        }
    }
    return message
}

func usageColor(_ percent: Int) -> Color { percent >= 80 ? .red : percent >= 50 ? .orange : .green }

func resetText(_ date: Date?) -> String {
    guard let date else { return "" }
    let s = max(0, Int(date.timeIntervalSinceNow))
    if s >= 86400 {
        let h = s % 86400 / 3600
        let day = tr("d", "j")
        return h > 0 ? "\(s / 86400)\(day) \(h)h" : "\(s / 86400)\(day)"
    }
    let minute = tr("m", "min")
    if s >= 3600 { return "\(s / 3600)h \(s % 3600 / 60)\(minute)" }
    return "\(s / 60)\(minute)"
}

func resetDate(_ date: Date?) -> String {
    guard let date else { return "" }
    let f = DateFormatter()
    f.locale = Language.current.locale
    let cal = Calendar.current
    if cal.isDateInToday(date) { f.dateFormat = tr("'today' HH:mm", "'aujourd’hui' HH:mm") }
    else if cal.isDateInTomorrow(date) { f.dateFormat = tr("'tomorrow' HH:mm", "'demain' HH:mm") }
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

/// Runs bin/cx or bin/ccx (Python scripts) and returns stdout.
func runTool(_ path: String, _ args: [String]) -> Data {
    let process = Process()
    process.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
    process.arguments = [path] + args
    // Tells cx it runs under the app: it then stops the Codex daemon instead of restarting it (see stop_daemon).
    process.environment = ProcessInfo.processInfo.environment.merging(["AI_USAGE_APP": "1"]) { $1 }
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
    f.locale = Language.current.locale
    f.dateFormat = "d MMM"
    return f.string(from: date)
}

func parseCodex(_ data: Data) -> [Account]? {
    guard let list = (try? JSONSerialization.jsonObject(with: data)) as? [[String: Any]] else { return nil }
    return list.map { a in
        let windows = (a["windows"] as? [[String: Any]] ?? []).map { w in
            UsageWindow(
                label: windowLabel(seconds: Int(number(w["limit_window_seconds"]) ?? 0)),
                percent: Int(number(w["used_percent"]) ?? 0),
                resetAt: number(w["reset_at"]).map { Date(timeIntervalSince1970: $0) })
        }
        return Account(
            brand: .openai,
            name: a["name"] as? String ?? "?",
            email: a["email"] as? String ?? "",
            plan: a["plan"] as? String ?? "",
            active: a["active"] as? Bool ?? false,
            error: a["error"] as? String,
            limitReached: a["limit_reached"] as? Bool ?? false,
            windows: windows,
            resets: (a["resets"] as? [String] ?? []).compactMap(parseISODate),
            lastSeen: number(a["last_seen"]).map { Date(timeIntervalSince1970: $0) })
    }
}

func parseClaude(_ data: Data) -> [Account]? {
    guard let list = (try? JSONSerialization.jsonObject(with: data)) as? [[String: Any]] else { return nil }
    return list.map { a in
        let windows: [UsageWindow] = (a["windows"] as? [[String: Any]] ?? []).map { w in
            let reset = (w["resets_at"] as? String).flatMap(parseISODate)
            let elapsed = reset.map { $0 < Date() } ?? false  // last known usage from a window that has reset
            return UsageWindow(
                label: w["label"] as? String ?? "?",
                percent: elapsed ? 0 : Int(number(w["percent"]) ?? 0),
                resetAt: elapsed ? nil : reset)
        }
        return Account(
            brand: .claude,
            name: a["name"] as? String ?? "?",
            email: a["email"] as? String ?? "",
            plan: a["plan"] as? String ?? "",
            active: a["active"] as? Bool ?? false,
            error: a["error"] as? String,
            limitReached: false,
            windows: windows,
            resets: [],
            lastSeen: number(a["last_seen"]).map { Date(timeIntervalSince1970: $0) })
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

/// The last Claude usage the app showed (ccx's active account or the usage API), kept in
/// UserDefaults: shown as a last resort when nothing can be read (launched offline, no token).
struct SavedClaudeUsage: Codable {
    struct Window: Codable {
        let label: String
        let percent: Int
        let resetAt: Date?
    }
    let at: Date
    let windows: [Window]
}

// MARK: - Model

@MainActor
final class UsageModel: ObservableObject {
    @Published var claude: [UsageWindow] = []
    @Published var claudeUpdated: Date?
    @Published var codex: [Account] = []
    @Published var codexFailed = false
    @Published var claudeAccounts: [Account] = []  // from ccx; rows shown once 2+ accounts are saved
    @Published var claudeUnused = false  // last Claude refresh ended with no account nor data
    @Published var codexLoaded = false
    @Published var loading = false
    @Published var switching: String?  // Account.key being switched to
    @Published var notes: [Brand: String] = [:]  // e.g. apps or sessions to restart after a switch
    private var expectedClaude: String?  // account chosen in the app, to detect a switch undone by a session
    @Published var menuBarImage = NSImage()
    private var lastRefresh = Date.distantPast
    private var timer: Timer?
    private var auth: ClaudeAuth?  // cached until it expires or fails, to skip a `security` run per refresh
    private var menuBarKey: String?
    private var appearanceObservation: NSKeyValueObservation?

    private let live: Bool
    private let defaults: UserDefaults
    static let lastClaudeKey = "lastClaudeUsage"

    /// `live: false` builds an empty model that never fetches (used to render screenshots).
    init(live: Bool = true, defaults: UserDefaults = .standard) {
        self.live = live
        self.defaults = defaults
        guard live else { return }
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
        guard live else { return }
        guard !loading else { return }
        loading = true
        lastRefresh = Date()
        Task {
            // Saved Claude accounts (ccx) already carry the active account's live usage; reading the
            // usage API here too would double the calls on a rate-limited endpoint.
            let accounts = await Task.detached { parseClaude(runTool(ccxPath, ["json"])) }.value
            if let accounts { claudeAccounts = accounts }
            checkClaudeSwitch()
            var answered = accounts != nil  // a failed ccx or usage API call says nothing about Claude being unused
            if let active = claudeAccounts.first(where: \.active) {
                claude = active.windows
                claudeUpdated = active.lastSeen ?? Date()
                if accounts != nil { rememberClaude() }  // not when ccx failed: same windows, no new reading
            } else if !(await refreshClaudeFromKeychain()) {
                answered = false
                // Nothing read yet (e.g. launched offline): the last usage the app read.
                if claude.isEmpty { (claude, claudeUpdated) = lastKnownClaude() }
            }
            if answered { claudeUnused = claudeAccounts.isEmpty && claude.isEmpty }
            updateMenuBarImage()
        }
        Task.detached {
            let accounts = parseCodex(runTool(cxPath, ["json"]))
            await MainActor.run {
                self.loading = false
                self.codexFailed = accounts == nil
                self.codexLoaded = true
                if let accounts { self.codex = accounts }
                self.updateMenuBarImage()
            }
        }
    }

    /// A provider's card stays out of the panel once loaded with nothing to show (tool not used).
    var showsClaude: Bool { !claudeUnused || !claudeAccounts.isEmpty || !claude.isEmpty || notes[.claude] != nil }
    var showsCodex: Bool { !codexLoaded || !codex.isEmpty || codexFailed || notes[.openai] != nil }

    /// No active ccx account: read the usage API with Claude Code's own token.
    /// False when a token was found but the API didn't answer (429, offline): nothing learned.
    private func refreshClaudeFromKeychain() async -> Bool {
        if auth?.valid != true { auth = await Task.detached { claudeAuth() }.value }
        guard let token = auth?.token else {
            // No token (signed out, or expired until Claude Code runs again): the last usage read, if any.
            if claude.isEmpty { (claude, claudeUpdated) = lastKnownClaude() }
            return true
        }
        if let live = await fetchClaudeLive(token: token) {
            claude = live
            claudeUpdated = Date()
            rememberClaude()
            return true
        }
        auth = nil  // revoked or rotated by Claude Code: re-read the Keychain next time
        return false
    }

    /// Keeps the Claude usage just shown for `lastKnownClaude()`; written only when it changed (its
    /// time included, so in practice after each live read). An empty reading keeps the previous one.
    private func rememberClaude() {
        guard let at = claudeUpdated, !claude.isEmpty else { return }
        let saved = SavedClaudeUsage(at: at, windows: claude.map {
            SavedClaudeUsage.Window(label: $0.label, percent: $0.percent, resetAt: $0.resetAt)
        })
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys  // same reading, same bytes: the comparison below holds
        guard let data = try? encoder.encode(saved), data != defaults.data(forKey: Self.lastClaudeKey) else { return }
        defaults.set(data, forKey: Self.lastClaudeKey)
    }

    /// Last resort, read only when no saved account is active, the usage API can't be read (no
    /// token, or no answer) and nothing was read before. A window that has reset since shows 0 %.
    private func lastKnownClaude() -> (windows: [UsageWindow], updated: Date?) {
        guard let data = defaults.data(forKey: Self.lastClaudeKey),
              let saved = try? JSONDecoder().decode(SavedClaudeUsage.self, from: data)
        else { return ([], nil) }
        let now = Date()
        let windows = saved.windows.map { w -> UsageWindow in
            let elapsed = w.resetAt.map { $0 < now } ?? false
            return UsageWindow(label: w.label, percent: elapsed ? 0 : w.percent, resetAt: elapsed ? nil : w.resetAt)
        }
        return (windows, saved.at)
    }

    /// An open Claude Code session refreshing its token can write the previous account back.
    private func checkClaudeSwitch() {
        guard let expected = expectedClaude,
              let active = claudeAccounts.first(where: \.active), active.name != expected else { return }
        notes[.claude] = "An open Claude Code session switched back to \(active.name). Close it, then switch again."
        expectedClaude = nil
    }

    func switchTo(_ account: Account) {
        guard !account.active, switching == nil else { return }
        switching = account.key
        notes[account.brand] = nil
        Task.detached {
            let output = String(decoding: runTool(account.brand.tool, ["use", account.name]), as: UTF8.self)
            let note = output.split(separator: "\n")
                .first { $0.hasPrefix("NOTE: ") }
                .map { String($0.dropFirst(6)) }
            await MainActor.run {
                self.switching = nil
                self.notes[account.brand] = note
                if account.brand == .claude { self.expectedClaude = account.name }
                self.refresh()
            }
        }
    }

    func addAccount(_ brand: Brand) {
        // A .command file opens in Terminal without needing Automation permission.
        let tool = brand == .claude ? "ccx" : "cx"
        let url = FileManager.default.temporaryDirectory.appendingPathComponent("ai-usage-add-\(tool).command")
        let script = "#!/bin/zsh\nexport PATH=\"$HOME/.local/bin:$PATH\"\n\(tool) add\necho\nread -k 1 '?Press any key to close'\n"
        try? script.write(to: url, atomically: true, encoding: .utf8)
        try? FileManager.default.setAttributes([.posixPermissions: 0o755], ofItemAtPath: url.path)
        NSWorkspace.shared.open(url)
    }

    private func menuBarChoice(_ brand: Brand) -> String {
        defaults.string(forKey: brand.menuBarChoiceKey) ?? ""
    }

    /// Appearance of the menu bar itself (it follows the wallpaper, not the app), read from the
    /// status item's window; re-renders the label whenever it changes.
    private func menuBarIsDark() -> Bool {
        if let window = NSApp.windows.first(where: { $0.className.contains("StatusBarWindow") }) {
            if appearanceObservation == nil {
                appearanceObservation = window.observe(\.effectiveAppearance) { [weak self] _, _ in
                    Task { @MainActor in self?.updateMenuBarImage() }
                }
            }
            return window.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
        }
        return NSApp.effectiveAppearance.bestMatch(from: [.darkAqua, .aqua]) == .darkAqua
    }

    /// Also called by the settings when the limit to show changes: no new read, just a redraw.
    func updateMenuBarImage() {
        var items: [MenuBarLabel.Item] = []
        if let shown = menuBarWindow(claude, choice: menuBarChoice(.claude)) {
            items.append(.init(brand: .claude, percent: shown.percent))
        }
        if let active = codex.first(where: \.active),
           let shown = menuBarWindow(active.windows, choice: menuBarChoice(.openai)) {
            items.append(.init(brand: .openai, percent: shown.percent))
        }
        // Each logo gets its own color; neutral items must still match the menu bar. A template
        // image does that by itself but can't hold colors, so colored labels are rendered with an
        // explicit neutral color picked from the menu bar's appearance.
        let colored = items.contains { $0.percent >= 50 }
        let dark = colored && menuBarIsDark()
        let key = items.map { "\($0.brand.resource)\($0.percent)" }.joined(separator: ",") + "|\(colored)|\(dark)"
        guard key != menuBarKey else { return }
        menuBarKey = key
        let label = MenuBarLabel(items: items, neutral: dark ? .white : .black, colored: colored)
        let renderer = ImageRenderer(content: label)
        renderer.scale = NSScreen.main?.backingScaleFactor ?? 2
        guard let image = renderer.nsImage else { return }
        image.isTemplate = !colored
        menuBarImage = image
    }
}

// MARK: - Views

struct MenuBarLabel: View {
    struct Item { let brand: Brand; let percent: Int }
    let items: [Item]
    let neutral: Color
    let colored: Bool  // false: template rendering, everything in `neutral`

    private func color(_ percent: Int) -> Color {
        guard colored else { return neutral }
        return percent >= 80 ? .red : percent >= 50 ? .orange : neutral
    }

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
                .foregroundStyle(color(items[i].percent))
            }
        }
        .foregroundStyle(neutral)
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

/// Shown instead of the cards when neither Claude Code nor Codex has anything to show.
struct NoAccountCard: View {
    var body: some View {
        VStack(spacing: 6) {
            Image(systemName: "gauge.with.needle").font(.system(size: 20)).foregroundStyle(.secondary)
            Text(tr("No accounts yet", "Aucun compte pour l’instant")).font(.system(size: 13, weight: .semibold))
            Text(tr("Add one with +, or save the one you’re signed in to with ccx\u{00A0}save or cx\u{00A0}save",
                    "Ajoutez-en un avec +, ou enregistrez celui auquel vous êtes connecté avec ccx\u{00A0}save ou cx\u{00A0}save"))
                .font(.system(size: 11)).foregroundStyle(.secondary).multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)  // wrap instead of truncating in the fitted panel
        }
        .padding(12)
        .frame(maxWidth: .infinity)
        .background(.quinary, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

struct UsageBar: View {
    let window: UsageWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .firstTextBaseline) {
                Text(windowName(window.label)).font(.system(size: 12))
                Spacer()
                Text("\(window.percent)%").font(.system(size: 12, weight: .semibold)).monospacedDigit()
            }
            Bar(percent: window.percent)
            if window.resetAt != nil {
                ResetLine(prefix: tr("Resets in ", "Réinitialisation dans "), date: window.resetAt)
            }
        }
    }
}

struct AccountRow: View {
    let account: Account
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
                        Text(tr("Limit reached", "Limite atteinte")).font(.system(size: 10, weight: .semibold)).foregroundStyle(.red)
                    } else if let worst = account.worst {
                        Text("\(worst.percent)%").font(.system(size: 12, weight: .semibold)).monospacedDigit()
                    }
                }
                // "Last seen" already says the usage couldn't be read; other errors (expired token, HTTP) stay.
                if let error = account.error, !(account.lastSeen != nil && error == "usage unreachable") {
                    Text(localized(error)).font(.system(size: 10)).foregroundStyle(.secondary).padding(.leading, 22)
                }
                ForEach(account.windows) { w in
                    VStack(alignment: .leading, spacing: 4) {
                        Bar(percent: w.percent)
                        ResetLine(prefix: windowName(w.label) + tr(" · resets in ", " · dans "), date: w.resetAt)
                    }
                    .padding(.leading, 22)
                }
                if let lastSeen = account.lastSeen {
                    Text(tr("Last seen ", "Dernier relevé ") + resetDate(lastSeen))
                        .font(.system(size: 10)).foregroundStyle(.tertiary).padding(.leading, 22)
                }
                if let first = account.resets.first {
                    HStack {
                        Label(freeResets(account.resets.count), systemImage: "arrow.counterclockwise")
                            .foregroundStyle(.secondary)
                        Spacer()
                        Text(tr("expires ", "expire le ") + shortDate(first)).foregroundStyle(.tertiary)
                    }
                    .font(.system(size: 10))
                    .padding(.leading, 22)
                    .help(tr("Expires: ", "Expiration : ") + account.resets.map(resetDate).joined(separator: ", "))
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
        .help(account.active
              ? tr("Active account", "Compte actif")
              : tr("Switch \(account.brand.product) to \(account.name)", "Basculer \(account.brand.product) sur \(account.name)"))
    }

    private func freeResets(_ count: Int) -> String {
        let s = count > 1 ? "s" : ""
        return tr("\(count) free reset\(s)", "\(count) reset\(s) gratuit\(s)")
    }
}

struct AccountList: View {
    @ObservedObject var model: UsageModel
    let accounts: [Account]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(accounts) { account in
                AccountRow(account: account, switching: model.switching == account.key) {
                    model.switchTo(account)
                }
            }
        }
    }
}

struct NoteLine: View {
    let text: String?

    var body: some View {
        if let text {
            Label(localized(text), systemImage: "info.circle")
                .font(.system(size: 10))
                .foregroundStyle(.secondary)
        }
    }
}

struct PanelView: View {
    @ObservedObject var model: UsageModel
    @State private var openAtLogin = SMAppService.mainApp.status == .enabled
    @AppStorage(Language.key) private var language = Language.current.rawValue
    @AppStorage(Theme.key) private var theme = Theme.system.rawValue
    @AppStorage(Brand.claude.menuBarChoiceKey) private var claudeChoice = ""
    @AppStorage(Brand.openai.menuBarChoiceKey) private var codexChoice = ""

    private var claudeNote: String? {
        guard let updated = model.claudeUpdated else { return nil }
        let minutes = Int(-updated.timeIntervalSinceNow / 60)
        if minutes < 1 { return tr("Just now", "À l’instant") }
        return minutes < 60 ? tr("\(minutes) min ago", "il y a \(minutes) min") : tr("\(minutes / 60) h ago", "il y a \(minutes / 60) h")
    }

    /// The panel and its menus; the menu bar label keeps following the menu bar itself.
    private func applyTheme() {
        NSApp.appearance = (Theme(rawValue: theme) ?? .system).appearance
    }

    private func menuBarPicker(_ title: String, _ choice: Binding<String>, _ windows: [UsageWindow]) -> some View {
        Picker(title, selection: choice) {
            Text(tr("Highest", "Le plus haut")).tag("")
            ForEach(menuBarChoices(windows, saved: choice.wrappedValue), id: \.self) { Text(windowName($0)).tag($0) }
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(tr("Usage", "Utilisation")).font(.system(size: 15, weight: .bold))
                Spacer()
                Menu {
                    Button(tr("Claude account…", "Compte Claude…")) { model.addAccount(.claude) }
                    Button(tr("Codex account…", "Compte Codex…")) { model.addAccount(.openai) }
                } label: {
                    Image(systemName: "plus")
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)
                .fixedSize()
                .help(tr("Add account", "Ajouter un compte"))
                if model.loading {
                    ProgressView().controlSize(.small)
                } else {
                    Button(action: model.refresh) { Image(systemName: "arrow.clockwise") }
                        .buttonStyle(.borderless)
                        .help(tr("Refresh", "Actualiser"))
                }
            }
            .padding(.horizontal, 2)

            if model.showsClaude {
                Card("Claude", brand: .claude, note: model.claudeAccounts.count > 1 ? nil : claudeNote) {
                    if model.claudeAccounts.count > 1 {
                        AccountList(model: model, accounts: model.claudeAccounts)
                    } else {
                        if model.claude.isEmpty {
                            Text(tr("No data yet — open Claude Code", "Pas encore de données — ouvrez Claude Code")).font(.system(size: 11)).foregroundStyle(.secondary)
                        }
                        ForEach(model.claude) { UsageBar(window: $0) }
                    }
                    NoteLine(text: model.notes[.claude])
                }
            }

            if model.showsCodex {
                Card("Codex", brand: .openai) {
                    if model.codexFailed {
                        Text(tr("Couldn't load accounts", "Impossible de charger les comptes")).font(.system(size: 11)).foregroundStyle(.red)
                    }
                    AccountList(model: model, accounts: model.codex)
                    NoteLine(text: model.notes[.openai])
                }
            }

            if !model.showsClaude && !model.showsCodex {
                NoAccountCard()
            }

            HStack {
                Menu {
                    Toggle(tr("Open at Login", "Ouvrir à la connexion"), isOn: $openAtLogin)
                    Picker(tr("Appearance", "Apparence"), selection: $theme) {
                        ForEach(Theme.allCases) { Text($0.name).tag($0.rawValue) }
                    }
                    Picker(tr("Language", "Langue"), selection: $language) {
                        ForEach(Language.allCases) { Text($0.name).tag($0.rawValue) }
                    }
                    if model.showsClaude {
                        menuBarPicker(tr("Claude in menu bar", "Claude dans la barre"), $claudeChoice, model.claude)
                    }
                    if model.showsCodex {
                        menuBarPicker(tr("Codex in menu bar", "Codex dans la barre"), $codexChoice,
                                      model.codex.first(where: \.active)?.windows ?? [])
                    }
                } label: {
                    Image(systemName: "gearshape")
                }
                .menuStyle(.borderlessButton)
                .menuIndicator(.hidden)
                .fixedSize()
                .help(tr("Settings", "Réglages"))
                Spacer()
                Button(tr("Quit", "Quitter")) { NSApp.terminate(nil) }.buttonStyle(.borderless)
            }
            .font(.system(size: 11))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 2)
            .onChange(of: openAtLogin) { _, enabled in
                let isEnabled = SMAppService.mainApp.status == .enabled
                guard enabled != isEnabled else { return }
                do {
                    if enabled { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
                } catch {
                    openAtLogin = isEnabled
                }
            }
        }
        .id(language)  // strings are computed, not observed: rebuild the panel when the language changes
        .onAppear { applyTheme() }
        .onChange(of: theme) { _, _ in applyTheme() }
        .onChange(of: claudeChoice) { _, _ in model.updateMenuBarImage() }
        .onChange(of: codexChoice) { _, _ in model.updateMenuBarImage() }
        .padding(12)
        .frame(width: 300)
        .onReceive(NotificationCenter.default.publisher(for: NSWindow.didBecomeKeyNotification)) { _ in
            model.refreshIfStale()
        }
    }
}

// MARK: - App

#if !SCREENSHOTS  // tools/screenshots provides its own entry point
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
#endif
