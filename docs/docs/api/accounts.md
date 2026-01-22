---
id: 'accounts'
title: 'Account Management'
sidebar_position: 2
description: 'Account management commands'
tags: ['api', 'accounts', 'cli']
---

# Account Management API

Manage Telegram accounts and their configuration.

## Commands

### Import Accounts

```bash
python -m tgarchive accounts --import
```

Imports accounts from `gen_config.py` (TELESMASHER-compatible format).

### List Accounts

```bash
python -m tgarchive accounts --list
```

Lists all configured accounts and their status.

### Test Accounts

```bash
python -m tgarchive accounts --test
```

Tests connectivity for all configured accounts.

### Reset Statistics

```bash
python -m tgarchive accounts --reset
```

Resets account usage statistics.
