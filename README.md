# NSE + BSE Order-Win Alerts → Telegram

Checks NSE and BSE corporate announcements every 5 minutes (market days, ~08:30–21:25 IST) and sends a Telegram message whenever a company announces an order win, contract, LoA/LoI, work order, etc.

## Setup (about 5 minutes)

1. **Create the bot**: in Telegram, message `@BotFather` → `/newbot` → copy the bot token.
2. **Get your chat ID**: send any message to your new bot, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `message.chat.id`.
   (For a channel/group: add the bot as admin/member and use that chat's ID, e.g. `-100...`.)
3. **Create a GitHub repo** and upload these files, keeping this layout:
   ```
   alerts.py
   requirements.txt
   .github/workflows/order-alerts.yml
   ```
4. **Add secrets**: repo → Settings → Secrets and variables → Actions → New repository secret:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
5. **Run it once**: Actions tab → "Order win alerts" → Run workflow. The first run seeds today's existing announcements silently and sends a "bot is live" message. After that, only new matches are alerted.

## How it works

- `alerts.py` pulls today's announcements from the BSE and NSE public APIs, filters them with the `INCLUDE` / `EXCLUDE` regexes, and posts matches to Telegram.
- `seen.json` (committed back to the repo by the workflow) remembers what was already sent, so you never get duplicates.

## Tuning

- Edit `INCLUDE` / `EXCLUDE` in `alerts.py` to widen or narrow what counts as an order win.
- Change the schedule in the workflow's `cron` line (GitHub cron is in UTC; IST = UTC+5:30).

## Things to know

- GitHub Actions cron is best-effort: runs can be delayed by a few minutes at busy times, so alerts are near-real-time, not instant. For true real-time, run `alerts.py` in a loop on an always-on server instead.
- NSE and BSE don't offer official public APIs. This uses the same endpoints their websites use, and NSE sometimes blocks cloud IPs (including GitHub's). The script keeps going if one exchange fails and logs which one. If NSE is blocked often, BSE alone still covers most listed companies.
- Alerts are a keyword filter on announcement text. Always read the filing before acting; this is not investment advice.
