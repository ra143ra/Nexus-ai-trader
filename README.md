# NEXUS AI TRADER — Stage 5: Risk-controlled paper trading

## Added in Stage 5
- Persistent SQLite paper account, positions and trade history.
- Paper bot enable/disable controls.
- One-tick evaluation endpoint using public Binance price data + the hybrid rule engine.
- Long-only spot simulation with 10% maximum account allocation per position.
- 2% daily equity-loss circuit breaker (automatically disables the paper bot).
- 2% stop-loss and 4% take-profit from simulated entry.
- Trading fees are included in simulated fills.
- Live exchange trading remains hard-disabled.

## Run the backend
Python 3.11+ recommended:
```bash
cd backend
python -m venv .venv
# activate environment
pip install -r requirements.txt
uvicorn app:app --reload
```
API docs: `http://127.0.0.1:8000/docs`

## Paper workflow
1. `POST /paper-bot/start` — enable paper simulation.
2. `POST /paper-bot/tick/BTCUSDT?interval=1h` — fetch current public price, calculate hybrid signal, and simulate an action if rules permit.
3. `GET /paper-bot/status` — inspect cash, equity and open positions.
4. `GET /paper-bot/trades` — inspect trade ledger.
5. `POST /paper-bot/stop` — disable the paper bot.

**Important:** A tick is an explicit evaluation request. This build does not run a continuous scheduler or Android background service. Do not interpret this as unattended automatic trading. SQLite data is stored in `backend/nexus_paper.db` when launched from the backend directory.

## Risk and limitations
- Simulation only. There is no authenticated exchange connection, no API-key support, and no live order endpoint.
- The strategy is a transparent rules engine, not trained AI and not a profit guarantee.
- Stop-loss and take-profit are evaluated only when a tick is submitted; gaps/slippage can make real fills worse.
- One open position maximum; long-only spot; no leverage, futures, shorts, or borrowing.
- Daily loss circuit breaker uses the account's local server date and only sees prices on explicit ticks.
- This is a development prototype. Run tests, paper-trade for an extended period, review logs, and obtain independent financial/regulatory advice before considering real funds. Check exchange availability, Indian rules and tax treatment.
- Never paste API keys or secrets into chat. Live trading is intentionally not implemented.

## Android
Open `android/` in Android Studio. The current Android screen remains a market-data dashboard scaffold; Stage 5 paper-bot controls are available through the backend API but are not yet wired into the app. Emulator backend URL is `http://10.0.2.2:8000`; physical devices require your computer's LAN IP and a trusted network. Use HTTPS for deployed services.


## Stage 6 — Android paper-bot controls
The Android dashboard now calls the paper-bot status/start/stop/tick endpoints and displays paper cash, equity, positions and hybrid signals. Each asset has an explicit **Evaluate Paper Tick** button. The app does not run a background trading loop.

### Android build
Open the `android/` folder in Android Studio, allow Gradle sync, then run the `app` configuration on an emulator. The emulator expects the backend at `http://10.0.2.2:8000`. A physical phone needs a reachable backend host address and should use HTTPS outside a trusted local development network. This source package does not include a verified APK.


## Stage 7 — background paper loop and optional Telegram alerts
- Backend starts a background polling loop at startup. It evaluates BTCUSDT, ETHUSDT and SOLUSDT every 5 minutes by default, but only while the paper bot is enabled.
- Change `NEXUS_SYMBOLS` and `NEXUS_POLL_SECONDS` environment variables if required (polling is clamped to at least 60 seconds).
- Optional Telegram alerts: set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as server environment variables. Never paste the bot token into this chat or commit it into source control.
- Check `GET /paper-bot/scheduler` for scheduler and Telegram configuration status.
- Android can still manually evaluate ticks; background polling is hosted by the backend, not by the phone. The backend must remain online.
- Background mode is PAPER ONLY. There is no authenticated exchange client and no live order execution.

### Run with Telegram alerts (Linux/macOS shell)
```bash
export TELEGRAM_BOT_TOKEN='your-token'
export TELEGRAM_CHAT_ID='your-chat-id'
uvicorn app:app --host 127.0.0.1 --port 8000
```
Use a process manager/container host to keep the backend running. Do not expose the development server directly to the public internet.


## Stage 8 — APK build pipeline
This stage adds a GitHub Actions workflow at `.github/workflows/android-apk.yml`.
To produce an APK:
1. Upload this source project to a private GitHub repository.
2. Open **Actions** → **Build Android APK** → **Run workflow** (or push a change under `android/`).
3. Wait for the workflow to finish. Download the `nexus-ai-trader-debug-apk` artifact from the workflow run.
4. Install the debug APK on a test Android device only after reviewing Android's unknown-app installation warning.

The workflow builds a **debug/test APK**, not a Play Store release. This environment does not have Android SDK/Gradle installed, so an APK has not been built or device-tested here. The app's development API URL is the Android emulator loopback bridge; configure a secure reachable API URL before using a physical device. Do not publish the development server or expose it directly to the internet.


## Stage 9 — build validation and network safety
- GitHub Actions now runs backend tests first, then attempts the Android debug APK build.
- Release/main Android manifest denies cleartext HTTP. Only the debug manifest allows HTTP for local emulator development.
- Debug APK is for testing only. Do not distribute it as a production app.
- To connect a physical phone, the app's development server URL must be changed to a secure HTTPS API endpoint; do not expose the local development server publicly.
- A successful workflow run is required before calling the APK build verified. No APK is included in this source ZIP.


## Stage 10 — Android source review
- Corrected Kotlin currency-label string interpolation and refreshed the in-app build label.
- This is a source-level correction only. The Android Gradle build still needs to run in GitHub Actions or Android Studio before the APK can be considered build-verified.
