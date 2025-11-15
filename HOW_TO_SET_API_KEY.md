# How to Set Telegram API Keys for SPECTRA

## 📱 Step 1: Get Your API Credentials

### Visit Telegram Developer Portal

1. Go to: **https://my.telegram.org/auth?to=apps**
2. Sign in with your **Telegram account** (the one you want to use with SPECTRA)
3. Enter your phone number and verify with the code Telegram sends

### Create or View Application

1. Click **"API development tools"** in the left menu
2. If prompted, fill in:
   - **App title:** e.g., "SPECTRA Recovery"
   - **Short name:** e.g., "spectra"
3. Accept the terms and click **"Create my application"**

### Copy Your Credentials

You will see:
- **api_id:** A numeric ID (e.g., `12345678`)
- **api_hash:** An alphanumeric string (e.g., `abcdef1234567890abcdef1234567890`)

**Keep these secure!** They're like passwords.

---

## 🔑 Step 2: Add to SPECTRA Configuration

### Edit `spectra_config.json`

Open the file in your editor:

```bash
nano spectra_config.json
# or
vim spectra_config.json
# or use any text editor
```

### Update the Accounts Section

Find the `accounts` array and add your credentials:

```json
{
  "accounts": [
    {
      "api_id": 12345678,
      "api_hash": "abcdef1234567890abcdef1234567890",
      "session_name": "account1",
      "phone_number": "+1234567890",
      "password": ""
    }
  ]
}
```

**Important fields:**
- `api_id` → Your numeric API ID
- `api_hash` → Your alphanumeric API hash
- `phone_number` → Phone number of the Telegram account
- `session_name` → Unique name for this account (use lowercase, no spaces)
- `password` → Leave blank unless you have 2FA enabled

### Example with Multiple Accounts

```json
{
  "accounts": [
    {
      "api_id": 12345678,
      "api_hash": "abcdef1234567890abcdef1234567890",
      "session_name": "recovery_account",
      "phone_number": "+1234567890",
      "password": ""
    },
    {
      "api_id": 12345678,
      "api_hash": "abcdef1234567890abcdef1234567890",
      "session_name": "backup_account",
      "phone_number": "+0987654321",
      "password": "YOUR_2FA_PASSWORD"
    }
  ]
}
```

### Example with 2FA Enabled

If your Telegram account has **two-factor authentication**:

```json
{
  "accounts": [
    {
      "api_id": 12345678,
      "api_hash": "abcdef1234567890abcdef1234567890",
      "session_name": "secure_account",
      "phone_number": "+1234567890",
      "password": "your_2fa_password_here"
    }
  ]
}
```

---

## 🌍 Step 3: Alternative: Use Environment Variables

Instead of storing in config file, use environment variables (more secure):

### Linux/macOS

```bash
export TG_API_ID=12345678
export TG_API_HASH="abcdef1234567890abcdef1234567890"

# Then run SPECTRA
spectra accounts --test
```

### Permanently Save (Linux/macOS)

Add to `~/.bashrc` or `~/.zshrc`:

```bash
export TG_API_ID=12345678
export TG_API_HASH="abcdef1234567890abcdef1234567890"
```

Then reload:
```bash
source ~/.bashrc
```

### Windows (PowerShell)

```powershell
$env:TG_API_ID = "12345678"
$env:TG_API_HASH = "abcdef1234567890abcdef1234567890"

# Check it worked
echo $env:TG_API_ID
```

---

## ✅ Step 4: Verify Configuration

### Test Connectivity

```bash
# Activate virtual environment first
source .venv/bin/activate

# Test the account
spectra accounts --test
```

Expected output:
```
✓ account1: Connected
✓ account2: Connected
```

### First-Time Authentication

When SPECTRA connects with a new session, it will prompt you:

```
Please enter your phone number (or Telegram account ID):
+1234567890

Please enter the authentication code:
12345

(If you have 2FA enabled, you'll also be asked for the password)
```

After authentication, the session is saved and reused automatically.

---

## 🔒 Security Best Practices

### 1. Keep API Hash Secret

**Never:**
- Commit to git
- Share with anyone
- Post in public forums

**Do:**
- Keep in secure location
- Use environment variables for servers
- Use different API keys for testing vs production

### 2. Restrict File Permissions

```bash
chmod 600 spectra_config.json
```

This prevents other users from reading your API keys.

### 3. Use .gitignore

Add to `.gitignore`:

```bash
# Config with API keys
spectra_config.json

# Session files (store auth tokens)
*.session
*.session-journal

# Logs that might contain sensitive info
logs/
```

### 4. Create a Template for Git

Track a safe template:

```bash
# Create template
cp spectra_config.json spectra_config.json.example

# Edit example to remove secrets
nano spectra_config.json.example
# Replace values with PLACEHOLDER_HERE

# Add to git
git add spectra_config.json.example
git commit -m "Add config template (no secrets)"
```

---

## 🔧 Troubleshooting

### Issue: "Account not authorized"

**Problem:** API ID or hash is incorrect

**Solution:**
1. Go back to https://my.telegram.org/apps
2. Copy the exact values again
3. Make sure there are no extra spaces
4. Verify the account is the one you want to use

### Issue: "Invalid session"

**Problem:** Session file is corrupted or old

**Solution:**
```bash
# Delete session files
rm *.session
rm *.session-journal

# Re-authenticate
spectra accounts --test
```

### Issue: "2FA password required"

**Problem:** Account has two-factor authentication

**Solution:**
1. Get your 2FA password from Telegram
2. Add to config:
```json
{
  "password": "your_2fa_password"
}
```

### Issue: "Unauthorized user"

**Problem:** Phone number doesn't match Telegram account

**Solution:**
1. Make sure phone number has country code (e.g., `+1234567890`)
2. Make sure it matches the Telegram account
3. Check that this phone number is verified in Telegram

### Issue: "API error: FLOOD_WAIT"

**Problem:** Too many login attempts

**Solution:**
- Wait a few minutes before retrying
- Set up a proxy if you have many accounts
- Increase delays in configuration

---

## 📋 Complete Configuration Example

Here's a complete working `spectra_config.json` with API keys:

```json
{
  "accounts": [
    {
      "api_id": 12345678,
      "api_hash": "abcdef1234567890abcdef1234567890",
      "session_name": "recovery_account",
      "phone_number": "+1234567890",
      "password": ""
    },
    {
      "api_id": 12345678,
      "api_hash": "abcdef1234567890abcdef1234567890",
      "session_name": "backup_account",
      "phone_number": "+0987654321",
      "password": "my_2fa_password"
    }
  ],
  "default_forwarding_destination_id": -1001234567890,
  "forwarding": {
    "enable_deduplication": true,
    "secondary_unique_destination": null,
    "auto_invite_accounts": true
  },
  "db": {
    "path": "spectra.db"
  },
  "logging": {
    "level": "INFO",
    "file": "spectra.log"
  }
}
```

---

## 🔄 Getting a New API Key (if Lost/Compromised)

If your API hash is compromised:

1. Go to https://my.telegram.org/apps
2. Click on your application
3. There's usually an option to regenerate the hash
4. Update `spectra_config.json` with the new hash

---

## ⚠️ Common Mistakes

| Mistake | Problem | Solution |
|---------|---------|----------|
| Missing country code | `+1234567890` instead of `+11234567890` | Add country code prefix |
| Extra spaces | `"api_hash": " abc123 "` | Remove leading/trailing spaces |
| Wrong quote type | `'api_hash': 'abc123'` | Use double quotes in JSON |
| Comma missing | Last account has no comma | Add comma after each object except the last |
| Wrong phone number | Using a different account's number | Use the phone number that was used to create the API ID |
| Storing in git | Committing `spectra_config.json` | Add to `.gitignore` immediately |

---

## 🎯 Next Steps After API Setup

1. **Verify:** `spectra accounts --test`
2. **Update channels:** `spectra channels update-access`
3. **Set recovery destination:** `spectra config set-forward-dest <channel_id>`
4. **Start recovery:** Use TUI Forwarding → Channel Recovery Wizard

---

## 📞 Support

If you're having trouble with API keys:

1. **Check the troubleshooting section** above
2. **Verify your credentials** on https://my.telegram.org
3. **Check the installation log** in `logs/`
4. **Try with environment variables** (more reliable for testing)
5. **Make sure phone number matches** the Telegram account

---

## 🆓 Multiple Accounts

SPECTRA can use multiple Telegram accounts simultaneously:

```json
{
  "accounts": [
    {
      "api_id": 12345678,
      "api_hash": "api_hash_1",
      "session_name": "account1",
      "phone_number": "+1111111111",
      "password": ""
    },
    {
      "api_id": 12345678,
      "api_hash": "api_hash_1",
      "session_name": "account2",
      "phone_number": "+2222222222",
      "password": ""
    },
    {
      "api_id": 87654321,
      "api_hash": "api_hash_2",
      "session_name": "account3",
      "phone_number": "+3333333333",
      "password": ""
    }
  ]
}
```

**Note:** You can use the **same API ID and hash** for multiple accounts (same app), or different API IDs (different apps).

For channel recovery, using multiple accounts is **recommended** because:
- Each account can access different channels
- If one account is banned, others continue working
- Better distribution of requests

---

**You're all set! SPECTRA will now authenticate with your Telegram account.** 🎉
