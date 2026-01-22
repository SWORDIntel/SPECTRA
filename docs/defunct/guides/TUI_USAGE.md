# TUI Usage Guide

SPECTRA provides a powerful Terminal User Interface (TUI) as the primary way to interact with the system. The TUI offers an intuitive, menu-driven interface for all major operations.

## Launching the TUI

```bash
# Launch the interactive TUI
python -m tgarchive

# Or use the launcher script
./spectra.sh

# Or use make
make run
```

## Main Menu Overview

When you launch SPECTRA, you'll see the main menu with the following options:

1. **Dashboard** - View system status, account health, and operation statistics
2. **Archive Channel/Group** - Archive messages and media from a specific channel or group
3. **Discover Groups** - Discover new groups and channels from seed entities
4. **Network Analysis** - Analyze group relationships and identify high-value targets
5. **Forwarding Utilities** - Forward messages between channels with deduplication
6. **OSINT Utilities** - Intelligence gathering and analysis tools
7. **Group Mirroring** - Mirror groups and channels
8. **Account Management** - Full CRUD operations for Telegram accounts:
   - Add new accounts with validation
   - Edit existing accounts
   - Delete accounts with confirmation
   - Import accounts from gen_config.py files
   - Keyboard shortcuts for quick access (Ctrl+A/E/D/I/R)
   - Always-visible keyboard shortcuts display
9. **Settings (VPS Config)** - Configure VPS and system settings
10. **Forwarding & Deduplication Settings** - Configure forwarding behavior
11. **Download Users** - Download user information and profiles
12. **Help & About** - Access help documentation and system information
13. **Exit** - Exit the application

## Navigation

### Keyboard Shortcuts

- **Number keys (1-9)**: Jump directly to menu items from the main menu
- **Ctrl+D**: Open Dashboard
- **Ctrl+A**: Open Archive menu
- **Ctrl+F**: Open Forwarding menu
- **Ctrl+H**: Open Help
- **Ctrl+K**: Quick access menu (command palette)
- **Ctrl+Q**: Quit application
- **Esc**: Go back to previous menu
- **Tab / Shift+Tab**: Navigate between fields

### Quick Actions

- `qa` = Archive
- `qd` = Dashboard
- `qf` = Forwarding
- `qs` = Search
- `qg` = Graph/Network Analysis
- `qm` = Main Menu

## Common Workflows

### Archiving a Channel

1. From main menu, select **2. Archive Channel/Group** (or press `2`)
2. Enter the channel username (e.g., `@example_channel`) or ID
3. Configure archive options (date range, media types, etc.)
4. Start the archive operation
5. Monitor progress in real-time

### Discovering New Groups

1. From main menu, select **3. Discover Groups** (or press `3`)
2. Enter seed channel(s) or load from file
3. Set discovery depth (how many hops to explore)
4. Start discovery operation
5. View discovered groups in the database

### Network Analysis

1. From main menu, select **4. Network Analysis** (or press `4`)
2. Choose data source (database or crawler directory)
3. Configure analysis parameters
4. View network graph and priority targets
5. Export results for further analysis

### Forwarding Messages

1. From main menu, select **5. Forwarding Utilities** (or press `5`)
2. Choose forwarding mode (selective, total, or forwarding mode)
3. Configure source and destination channels
4. Set deduplication options
5. Start forwarding operation

### Account Management

1. From main menu, select **8. Account Management** (or press `8`)
2. View account status and health
3. Import accounts from `gen_config.py`
4. Test account connectivity
5. Manage account rotation settings

## Dashboard Features

The Dashboard (option 1) provides:

- **System Status**: Account availability, database status, active operations
- **Account Health**: Status of all configured Telegram accounts
- **Operation Statistics**: Recent operations, success rates, error counts
- **Quick Actions**: Fast access to common operations
- **Real-time Updates**: Live status updates during operations

## Tips for Using the TUI

- **Use keyboard shortcuts** for faster navigation
- **Check the Dashboard** regularly to monitor system health
- **Use the Help menu** (Ctrl+H) for context-sensitive help
- **All operations are resumable** - you can safely exit and resume later
- **Progress indicators** show real-time status for long operations
- **Error messages** provide clear guidance on how to resolve issues

## TUI vs CLI

The TUI provides the same functionality as the CLI but with a more user-friendly interface. All operations performed in the TUI use the same backend modules, ensuring consistency and reliability. For automation and scripting, you can still use the CLI commands (see [CLI Reference](../reference/CLI_REFERENCE.md)).
