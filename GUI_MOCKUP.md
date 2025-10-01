# SPECTRA GUI Mockup

## Main Menu Interface

```
╔═══════════════════════════════════════════════════════════════════════════╗
║                          ███████╗██████╗ ███████╗ ██████╗████████╗██████╗  ║
║                          ██╔════╝██╔══██╗██╔════╝██╔════╝╚══██╔══╝██╔══██╗ ║
║                          ███████╗██████╔╝█████╗  ██║        ██║   ██████╔╝ ║
║                          ╚════██║██╔═══╝ ██╔══╝  ██║        ██║   ██╔══██║ ║
║                          ███████║██║     ███████╗╚██████╗   ██║   ██║  ██║ ║
║                          ╚══════╝╚═╝     ╚══════╝ ╚═════╝   ╚═╝   ╚═╝  ╚═╝ ║
╚═══════════════════════════════════════════════════════════════════════════╝
               Telegram Network Discovery & Archiving System v3.0
                     Integrated Telegram Intelligence Platform

┌─────────────────────────────────────────────────────────────────────────────┐
│                                MAIN MENU                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   [1. Archive Channel/Group]        Archive individual channels            │
│   [2. Discover Groups]              Find connected channels/groups         │
│   [3. Network Analysis]             Visualize channel relationships        │
│   [4. Forwarding Utilities] ⭐      Message forwarding & organization       │
│   [5. OSINT Utilities]              Intelligence gathering tools           │
│   [6. Group Mirroring]              Mirror channel content                 │
│   [7. Account Management]           Configure Telegram accounts            │
│   [8. Settings (VPS Config)]        System configuration                   │
│   [9. Forwarding & Dedup Settings]  Advanced forwarding options           │
│   [10. Download Users]              Extract user data                      │
│   [11. Help & About]                Documentation & support                │
│   [12. Exit]                        Close application                      │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ Status: Ready - 3 accounts configured, 247 channels discovered             │
│ Database: /home/user/spectra.db (15.2 MB, 2,847 records)                  │
│ Last Operation: Forward completed - 156 messages, 23 files organized       │
└─────────────────────────────────────────────────────────────────────────────┘

                          [Tab] Navigate  [Enter] Select  [Ctrl+C] Exit
```

## Enhanced Forwarding Interface (NEW)

```
╔═══════════════════════════════════════════════════════════════════════════╗
║                            FORWARDING UTILITIES                          ║
╚═══════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────────┐
│                          FORWARDING CONFIGURATION                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ Source Channel:      [@channel_source_________________] [Browse]            │
│ Destination Channel: [@channel_destination____________] [Browse]            │
│ Account:            [📱 +1234567890 (Primary)        ▼] [Manage]            │
│                                                                             │
│ ┌─── TOPIC ORGANIZATION (NEW) ──────────────────────────────────────────┐   │
│ │                                                                        │   │
│ │ ☑ Enable Auto-Organization    ☐ Create sub-folders/topics             │   │
│ │                                                                        │   │
│ │ Organization Strategy: [Content Type              ▼]                   │   │
│ │   ├─ Content Type      (📁 Photos, 📄 Documents, 🎵 Audio)            │   │
│ │   ├─ Date Based        (📅 Daily, Weekly, Monthly topics)             │   │
│ │   ├─ File Extension    (📄 .pdf, 📦 .zip, 🎬 .mp4)                   │   │
│ │   ├─ Source Channel    (📺 Organize by origin)                        │   │
│ │   ├─ Custom Rules      (⚙️ User-defined patterns)                      │   │
│ │   └─ Hybrid            (🔀 Combine multiple strategies)               │   │
│ │                                                                        │   │
│ │ Organization Mode: [Auto-Create Topics           ▼]                    │   │
│ │   ├─ Auto-Create      (✨ Create topics automatically)               │   │
│ │   ├─ Existing Only    (📋 Use existing topics only)                   │   │
│ │   ├─ Hybrid           (🔄 Create if needed, use existing)             │   │
│ │   └─ Disabled         (❌ No organization)                            │   │
│ │                                                                        │   │
│ │ Topic Naming: [📁 {content_type}] [📅 {date}] [🏷️ {custom}]           │   │
│ │                                                                        │   │
│ └────────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│ ┌─── FORWARDING OPTIONS ────────────────────────────────────────────────┐   │
│ │ ☑ Enable Deduplication     ☐ Forward to All Saved Messages           │   │
│ │ ☑ Prepend Origin Info       ☐ Secondary Unique Destination            │   │
│ │ ☐ Total Mode (All Channels) ☑ Include Media Files                     │   │
│ └────────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│           [🚀 Start Forwarding]  [⚙️ Advanced]  [📊 Statistics]            │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ Preview: Will forward from @news_channel to @archive_main                   │
│          Content will be organized into topics by type:                     │
│          📁 Photos, 📄 Documents, 🎵 Audio, 🎬 Videos, 📦 Archives         │
└─────────────────────────────────────────────────────────────────────────────┘

                    [Tab] Navigate  [Enter] Select  [Esc] Back
```

## Forwarding Progress Interface

```
╔═══════════════════════════════════════════════════════════════════════════╗
║                          FORWARDING IN PROGRESS                          ║
╚═══════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────────┐
│                               OPERATION STATUS                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ Source: @news_channel → Destination: @archive_main                         │
│ Started: 2025-09-17 15:45:23 UTC                                           │
│                                                                             │
│ Overall Progress: ████████████████████████████████████████ 100% (2,847/2,847) │
│ Current Phase: [✅ Scanning] [✅ Classifying] [✅ Organizing] [🔄 Forwarding]  │
│                                                                             │
│ ┌─── TOPIC ORGANIZATION STATUS ─────────────────────────────────────────┐   │
│ │                                                                        │   │
│ │ 📁 Photos          ████████████████████████ 432 messages → Topic ID: 23│   │
│ │ 📄 Documents       ████████████████████ 387 messages → Topic ID: 24    │   │
│ │ 🎵 Audio          ████████████████ 156 messages → Topic ID: 25         │   │
│ │ 🎬 Videos         ████████████████████████████ 523 messages → Topic ID: 26│   │
│ │ 📦 Archives       ████████████ 89 messages → Topic ID: 27               │   │
│ │ 💬 Text Only      ████████████████████████████████████ 1,260 → Topic ID: 28│   │
│ │                                                                        │   │
│ │ Topics Created: 6/6    Topics Used: 6    Classification Rate: 98.4%    │   │
│ └────────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│ ┌─── REAL-TIME STATISTICS ──────────────────────────────────────────────┐   │
│ │ Messages Processed: 2,847      Duplicates Skipped: 156                │   │
│ │ Files Transferred: 1,587       Total Size: 4.2 GB                     │   │
│ │ Processing Speed: 45 msg/sec   Estimated Time: 2m 15s remaining       │   │
│ │ Success Rate: 99.2%            Errors: 23 (rate limited: 18)          │   │
│ └────────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│ Current Message: "📄 Research_Paper_v3.pdf (2.1 MB)"                      │
│ Action: Creating document topic → Forwarding to 📄 Documents               │
│                                                                             │
│                    [⏸️ Pause]  [⏹️ Stop]  [📊 Details]                    │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ Recent Activity:                                                            │
│ 15:47:32 ✅ Created topic "📁 Photos" with 432 messages                    │
│ 15:47:28 ✅ Created topic "📄 Documents" with 387 messages                 │
│ 15:47:15 ⚠️  Rate limit hit, waiting 30 seconds...                         │
│ 15:47:10 ✅ Classified 1,000 messages (95.2% confidence)                   │
└─────────────────────────────────────────────────────────────────────────────┘

                          [Esc] Stop  [Space] Pause/Resume
```

## Content Classification Demo

```
╔═══════════════════════════════════════════════════════════════════════════╗
║                        CONTENT CLASSIFICATION DEMO                       ║
╚═══════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────────┐
│                          INTELLIGENT CLASSIFICATION                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ Message #1: "Check out this amazing sunset! 🌅"                           │
│ ├─ Attachment: IMG_20250917_sunset.jpg (2.1 MB)                           │
│ ├─ Classification: 📁 PHOTOS (Confidence: 98.5%)                          │
│ ├─ Reason: Image file + photography keywords                               │
│ └─ Destination: Topic "📁 Photos" (ID: 23)                                │
│                                                                             │
│ Message #2: "Latest research findings attached"                            │
│ ├─ Attachment: research_paper_v3.pdf (4.7 MB)                             │
│ ├─ Classification: 📄 DOCUMENTS (Confidence: 95.2%)                       │
│ ├─ Reason: PDF file + academic keywords                                    │
│ └─ Destination: Topic "📄 Documents" (ID: 24)                             │
│                                                                             │
│ Message #3: "🎵 New album drop!"                                           │
│ ├─ Attachment: album_track_01.mp3 (8.2 MB)                                │
│ ├─ Classification: 🎵 AUDIO (Confidence: 99.1%)                           │
│ ├─ Reason: Audio file + music keywords + emoji                             │
│ └─ Destination: Topic "🎵 Audio" (ID: 25)                                 │
│                                                                             │
│ Message #4: "Backup files for the project"                                 │
│ ├─ Attachment: project_backup_2025.zip (156 MB)                           │
│ ├─ Classification: 📦 ARCHIVES (Confidence: 97.8%)                        │
│ ├─ Reason: Archive file + backup keywords                                  │
│ └─ Destination: Topic "📦 Archives" (ID: 27)                              │
│                                                                             │
│ Message #5: "Just a quick text update, no attachments"                     │
│ ├─ Classification: 💬 TEXT ONLY (Confidence: 100%)                        │
│ ├─ Reason: No attachments, plain text content                              │
│ └─ Destination: Topic "💬 Text Messages" (ID: 28)                         │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ Classification Rules Active: 8                Success Rate: 98.4%          │
│ Custom Rules: 2                              Processing Speed: 45 msg/sec  │
│ Confidence Threshold: 85%                    Topics Created: 6             │
└─────────────────────────────────────────────────────────────────────────────┘

                              [Enter] Continue  [Esc] Back
```

## Network Analysis Interface

```
╔═══════════════════════════════════════════════════════════════════════════╗
║                            NETWORK ANALYSIS                              ║
╚═══════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────────┐
│                          CHANNEL RELATIONSHIP MAP                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│     @news_hub ──────┐                   ┌─── @tech_talks                    │
│         │           │                   │        │                          │
│         │           ▼                   ▼        │                          │
│    @breaking_news ──────► @main_channel ◄──── @dev_chat                     │
│         │                      │                 │                          │
│         │                      ▼                 ▼                          │
│         └──► @local_news    @announcements   @code_reviews                  │
│                  │              │               │                           │
│                  ▼              ▼               ▼                           │
│              @weather      @events_cal     @project_updates                 │
│                                                                             │
│ Legend: ──► Forward Link  ◄── Back Link  ◄──► Mutual Link                  │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ Network Statistics:                                                         │
│ ├─ Channels Discovered: 247        ├─ Average Connections: 3.2             │
│ ├─ Active Connections: 1,856       ├─ Network Diameter: 6 hops             │
│ ├─ Hub Channels: 12                ├─ Clustering Coefficient: 0.73          │
│ └─ Isolated Channels: 15           └─ Last Scan: 2025-09-17 14:23 UTC      │
└─────────────────────────────────────────────────────────────────────────────┘

            [🔍 Search] [📊 Export] [🎯 Focus] [↻ Refresh] [Esc] Back
```

## Account Management Interface

```
╔═══════════════════════════════════════════════════════════════════════════╗
║                           ACCOUNT MANAGEMENT                             ║
╚═══════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────────┐
│                            TELEGRAM ACCOUNTS                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ ┌─ Account 1 ──────────────────────────────────────────────────────────┐   │
│ │ 📱 +1234567890 (Primary)     Status: ✅ Active                       │   │
│ │ Session: user_session_1.session                                      │   │
│ │ API ID: 1234567              API Hash: abc123***                     │   │
│ │ Last Used: 2025-09-17 15:45  Operations: 2,847                       │   │
│ │ Rate Status: 🟢 Normal       Proxy: None                             │   │
│ │ [Test] [Edit] [Remove] [Export Session]                              │   │
│ └───────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│ ┌─ Account 2 ──────────────────────────────────────────────────────────┐   │
│ │ 📱 +9876543210 (Secondary)   Status: ✅ Active                       │   │
│ │ Session: user_session_2.session                                      │   │
│ │ API ID: 7654321              API Hash: def456***                     │   │
│ │ Last Used: 2025-09-17 14:32  Operations: 1,205                       │   │
│ │ Rate Status: 🟡 Limited      Proxy: SOCKS5://proxy.example.com:1080  │   │
│ │ [Test] [Edit] [Remove] [Export Session]                              │   │
│ └───────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│ ┌─ Account 3 ──────────────────────────────────────────────────────────┐   │
│ │ 📱 +5555551234 (Backup)      Status: ❌ Offline                      │   │
│ │ Session: user_session_3.session                                      │   │
│ │ API ID: 5551234              API Hash: ghi789***                     │   │
│ │ Last Used: 2025-09-16 09:15  Operations: 456                         │   │
│ │ Rate Status: 🔴 Restricted   Proxy: None                             │   │
│ │ [Test] [Edit] [Remove] [Export Session]                              │   │
│ └───────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│        [➕ Add Account] [📁 Import from gen_config.py] [🔄 Test All]        │
│                                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│ Account Usage Statistics:                                                   │
│ Total Operations: 4,508          Successful: 4,385 (97.3%)                 │
│ Rate Limits Hit: 23              Current Rotation: Account 1               │
│ Average Response Time: 340ms     Next Rotation: In 2m 15s                  │
└─────────────────────────────────────────────────────────────────────────────┘

                    [Tab] Navigate  [Enter] Select  [Esc] Back
```

## Settings Configuration

```
╔═══════════════════════════════════════════════════════════════════════════╗
║                        FORWARDING & ORGANIZATION SETTINGS                ║
╚═══════════════════════════════════════════════════════════════════════════╝

┌─────────────────────────────────────────────────────────────────────────────┐
│                          TOPIC ORGANIZATION CONFIG                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│ ┌─── DEFAULT ORGANIZATION STRATEGY ─────────────────────────────────────┐   │
│ │ Primary Strategy: [Content Type              ▼]                       │   │
│ │ Secondary Strategy: [Date Based               ▼]                       │   │
│ │ Fallback Strategy: [None                     ▼]                       │   │
│ │                                                                        │   │
│ │ Topic Naming Template:                                                 │   │
│ │ [📁 {content_type}                                               ]     │   │
│ │ [📅 {date_format}                                               ]     │   │
│ │ [🏷️ {custom_tag}                                                ]     │   │
│ └────────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│ ┌─── CONTENT CLASSIFICATION RULES ──────────────────────────────────────┐   │
│ │                                                                        │   │
│ │ Rule 1: Media Type Detection                Status: ✅ Enabled        │   │
│ │ ├─ Photos: .jpg, .png, .gif, .webp          Confidence: 95%+          │   │
│ │ ├─ Videos: .mp4, .mkv, .avi, .mov           Priority: High            │   │
│ │ └─ Audio: .mp3, .flac, .wav, .ogg           [Edit] [Disable]          │   │
│ │                                                                        │   │
│ │ Rule 2: File Size Categories                 Status: ✅ Enabled        │   │
│ │ ├─ Tiny: 0-10KB    ├─ Small: 10KB-100KB     Confidence: 99%+          │   │
│ │ ├─ Medium: 100KB-10MB ├─ Large: 10MB-100MB   Priority: Medium          │   │
│ │ └─ Huge: 100MB+                              [Edit] [Disable]          │   │
│ │                                                                        │   │
│ │ Rule 3: Keyword Patterns                     Status: ✅ Enabled        │   │
│ │ ├─ Academic: research, paper, study          Confidence: 85%+          │   │
│ │ ├─ Code: github, repository, commit          Priority: High            │   │
│ │ └─ News: breaking, urgent, alert             [Edit] [Disable]          │   │
│ │                                                                        │   │
│ │ Custom Rule 4: [Add Custom Rule...]                                   │   │
│ └────────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│ ┌─── PERFORMANCE SETTINGS ──────────────────────────────────────────────┐   │
│ │ Classification Timeout: [5.0] seconds                                 │   │
│ │ Topic Cache TTL: [300] seconds                                         │   │
│ │ Max Topics per Channel: [50]                                           │   │
│ │ Confidence Threshold: [85]%                                            │   │
│ │ Auto-Cleanup Old Topics: ☑ Enabled (30 days)                         │   │
│ └────────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│              [💾 Save Settings] [🔄 Reset to Defaults] [🧪 Test]           │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘

                         [Tab] Navigate  [Enter] Modify  [Esc] Back
```

These mockups demonstrate:

1. **Professional Terminal Interface** - Clean, organized layout with clear navigation
2. **Enhanced Forwarding System** - New topic organization features prominently displayed
3. **Real-Time Progress** - Live status updates and detailed statistics
4. **Intelligent Classification** - Visual demonstration of content analysis
5. **Network Visualization** - ASCII-based relationship mapping
6. **Account Management** - Comprehensive multi-account interface
7. **Configuration System** - Detailed settings for customization

The GUI provides an intuitive interface for both basic users and advanced intelligence operations while maintaining the power of the underlying SPECTRA framework.