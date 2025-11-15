# 🚫 Deprecated Installers

## Summary

Two installers have been **deprecated** in favor of a new unified installer: **`install-spectra.sh`**

---

## Deprecated Files

### 1. ❌ `auto-install.sh` (CRITICAL BUG)

**Status:** **DEPRECATED - DO NOT USE**

**Critical Bug:**
```bash
Line 367: return install_dependencies_alternative
Error: "numeric argument required"
```

This bug causes the installation to fail when trying to install Python dependencies.

**Reason for Deprecation:**
- Critical bug in bash syntax (invalid return statement)
- Poor error handling
- Minimal progress feedback
- No configuration template generation
- Difficult to debug when errors occur

**What to do:**
- ❌ Do NOT run: `./auto-install.sh`
- ✅ Use instead: `./install-spectra.sh`

---

### 2. ⚠️ `install.sh` (DEPRECATED)

**Status:** **DEPRECATED - USE NEW INSTALLER INSTEAD**

**Reason for Deprecation:**
- Limited to simple installation without dependency progress feedback
- No real-time package installation display
- Limited error handling
- Outdated approach

**What to do:**
- ❌ Do NOT run: `./install.sh`
- ✅ Use instead: `./install-spectra.sh`

---

## ✅ Official Installer

### `install-spectra.sh` (RECOMMENDED)

**Status:** **OFFICIAL - USE THIS ONE**

**New Features:**
- ✅ Bug-free implementation
- ✅ Real-time dependency progress display
- ✅ System auto-detection (Linux/macOS/WSL)
- ✅ Comprehensive error handling
- ✅ Configuration template generation
- ✅ Installation verification
- ✅ Clear, helpful output messages
- ✅ Deprecation redirect from old installers

**Usage:**
```bash
./install-spectra.sh
```

**What it does:**
1. Detects your OS and package manager
2. Installs system dependencies (with progress)
3. Creates Python virtual environment
4. Installs Python packages (shown individually)
5. Sets up project structure
6. Generates configuration template
7. Verifies installation
8. Shows next steps

---

## Migration Guide

If you were using an old installer:

### If You Run `auto-install.sh`:

```
╔════════════════════════════════════════════════════════╗
║          ⚠️  DEPRECATED INSTALLER                     ║
║   THIS INSTALLER HAS A CRITICAL BUG - LINE 367        ║
╚════════════════════════════════════════════════════════╝

This installer (auto-install.sh) is deprecated and has a bug.

Critical Bug: return install_dependencies_alternative
  Error: numeric argument required

Do you want to run the new installer instead? (y/n)
```

**Answer:** `y` to proceed with the new installer

### If You Run `install.sh`:

```
╔════════════════════════════════════════════════════════╗
║          ⚠️  DEPRECATED INSTALLER                     ║
╚════════════════════════════════════════════════════════╝

This installer (install.sh) is deprecated.

A new, unified installer has been created with:
  ✓ Bug fixes
  ✓ Real-time dependency progress display
  ✓ Better error handling
  ✓ Improved documentation

Do you want to run the new installer instead? (y/n)
```

**Answer:** `y` to proceed with the new installer

---

## Quick Migration

**Step 1: Run the new installer**
```bash
./install-spectra.sh
```

**Step 2: Follow the prompts**
- The installer will handle all setup
- You'll see progress for each step
- Configuration template is created automatically

**Step 3: Configure API keys**
```bash
nano spectra_config.json
```

See `HOW_TO_SET_API_KEY.md` for detailed instructions.

**Step 4: Test the installation**
```bash
source .venv/bin/activate
spectra accounts --test
```

---

## Why These Changes?

### `auto-install.sh` Bug

The error "numeric argument required" occurs because of this line:
```bash
return install_dependencies_alternative  # ❌ WRONG
```

In bash, `return` only accepts numeric exit codes:
```bash
return 0   # ✅ CORRECT
return 1   # ✅ CORRECT
return 127 # ✅ CORRECT

return some_function  # ❌ WRONG - causes error
```

The fix is to properly call the function:
```bash
install_dependencies_alternative  # ✅ CORRECT
```

### Overall Improvements

New installer provides:
1. **Better UX:** Real-time progress showing each package
2. **Fewer Bugs:** Proper bash syntax throughout
3. **Better Docs:** Comprehensive guides included
4. **Easier Debugging:** Clear error messages
5. **Full Coverage:** Works on Linux, macOS, WSL

---

## What's Happening Now?

When you run an old installer:

1. **Deprecation notice is displayed** (2 seconds to read)
2. **Prompt to use new installer** (y/n)
3. **If "y":** Launches new installer automatically
4. **If "n":** Continues with old installer (not recommended)

---

## Files to Delete (Optional)

If you want to clean up, you can remove the old installers:

```bash
# Remove deprecated installers
rm install.sh
rm auto-install.sh

# This deprecation notice can be deleted too if you prefer
rm DEPRECATION.md
```

**But keep:** `./install-spectra.sh` (this is the official one)

---

## Questions?

1. **Which installer should I use?**
   - Answer: `./install-spectra.sh`

2. **What if the old installer had different features?**
   - Answer: The new installer includes all important features plus improvements

3. **Can I still use the old installer?**
   - Answer: You *can* (it will still run), but it's not recommended due to bugs

4. **Where do I report issues with the new installer?**
   - Answer: Check `INSTALLATION_GUIDE.md` troubleshooting section

---

## Timeline

| Date | Event |
|------|-------|
| **Now** | `install-spectra.sh` released as official installer |
| **Now** | `install.sh` marked deprecated (shows notice) |
| **Now** | `auto-install.sh` marked deprecated with bug notice |
| **Future** | Old installers may be removed entirely |

---

## Summary

```
OLD INSTALLERS          NEW INSTALLER
═══════════════════     ═══════════════════════════
❌ auto-install.sh      ✅ install-spectra.sh
❌ install.sh           (Unified, bug-free)
                        Real-time progress
                        Better documentation
                        Easier setup
```

**Use:** `./install-spectra.sh` ← THE ONLY ONE YOU NEED

---

**Thank you for using SPECTRA! Enjoy the improved installation experience.** 🚀
