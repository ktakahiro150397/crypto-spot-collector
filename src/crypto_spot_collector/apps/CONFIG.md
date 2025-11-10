# Configuration Files

This directory contains the main application scripts and their configuration files.

## Configuration Files

### secrets.json (API Keys - Private)
This file contains sensitive API keys and should never be committed to version control.

**Location**: `src/crypto_spot_collector/apps/secrets.json`

**Structure**:
```json
{
  "bybit": {
    "apiKey": "YOUR_BYBIT_API_KEY",
    "secret": "YOUR_BYBIT_SECRET_KEY"
  }
}
```

**Setup**: Copy `secrets.json.sample` to `secrets.json` and fill in your actual API keys.

### settings.json (Public Settings)
This file contains application settings that are not sensitive and can be shared publicly.

**Location**: `src/crypto_spot_collector/apps/settings.json`

**Structure**:
```json
{
  "settings": {
    "discordWebhookUrl": "https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN",
    "discordBotToken": "YOUR_DISCORD_BOT_TOKEN",
    "timeframes": [
      {
        "timeframe": "4h",
        "amountBuyUSDT": 10.0,
        "consecutivePositiveCount": 3
      },
      {
        "timeframe": "1d",
        "amountBuyUSDT": 20.0,
        "consecutivePositiveCount": 3
      }
    ]
  }
}
```

**Setup**: Copy `settings.json.sample` to `settings.json` and customize according to your needs.

## Setup Instructions

1. Copy the sample files:
```bash
cd src/crypto_spot_collector/apps
cp secrets.json.sample secrets.json
cp settings.json.sample settings.json
```

2. Edit `secrets.json` with your actual API keys:
   - Bybit API Key
   - Bybit Secret Key

3. Edit `settings.json` with your preferences:
   - Discord Webhook URL for notifications
   - Discord Bot Token (if using Discord bot)
   - Trading timeframes and amounts
   - Signal detection parameters

## Note
- `secrets.json` and `settings.json` are git-ignored for security
- Only `*.sample` files are tracked in version control
- Never commit actual API keys or tokens to the repository
