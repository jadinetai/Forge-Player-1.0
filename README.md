# Forge Player 0.50 — local release candidate

Your music, without the extra noise. This patches the working 0.45 Python/SQLite app and preserves its UI and library.

## Start

Windows, Python 3.11+: double-click **START_FORGE.bat**, then use **http://127.0.0.1:8766/** in your default browser. No extra Python package, firmware, domain or hosting purchase is needed. The server stays running after the terminal/browser closes. Start it again after reboot; no Windows startup service is installed.

Click **Sign in with Google**. Forge bundles its application-owned public Desktop client configuration; users do not create a Cloud project or upload JSON. OAuth uses the system browser, PKCE, state and a loopback callback. Tokens remain Windows-user-bound DPAPI ciphertext in `%LOCALAPPDATA%\ForgePlayer\credentials`. Refreshes, restarts and updates retain them. Revocation produces **Reauthorize Google**.

**Public-release blocker:** Google's live console on October 23, 2026 showed External / Testing, two approved test accounts and publishing disabled pending Branding configuration. Arbitrary new users cannot authorize yet. See HOSTING-v050.md. This is not a production-ready public release.

## Persistent data and offline operation

The default library is the Windows Documents known folder plus `Forge_Player\forge_player.sqlite3`, independent of the source/update folder. If Documents is redirected into OneDrive, the library follows those sync settings. Tokens remain in LocalAppData. `FORGE_DATA_DIR` changes the data folder; `--db` selects a database. Test servers should use `serve --isolated` to avoid the Windows account token store.

Local library reads and edits work offline while the backend runs. Streaming and Google sync require internet. Only the UI shell is cached: no video, tokens, history or API responses. A stopped backend shows instructions to open START_FORGE.bat and Reconnect. Writes are not queued against an unavailable server. A PWA manifest is supplied, but installation support depends on the browser.

## Playback

The visible official YouTube player owns playback, clock, pause and seek. Google API authorization does not sign the iframe into YouTube or grant age-restricted access. Error 100 is unavailable/private; 101/150 is embedding disallowed; 153 is missing referrer/client identification. Restricted uploads retain **Open original on YouTube**. No stream extraction, spoofed domain or restriction bypass is used.

Recovery searches up to 20 official candidates, caches results for 24 hours, limits explicit refresh to once per minute per recording and caps local searches at 90/day. Failure retry windows are six hours for 100 and 24 hours for 101/150, scoped to the browser. At most three automatic substitutes are tried per chain. Configuration/network/age-check failures do not launch search loops.

High confidence requires normalized title, corroborated artist, close duration and no version conflicts, scoring at least 90. Medium needs a choice; low is never automatic. Album/recording identifiers are compared when available. **Correct match / Wrong match** remembers the exact recording/upload pair separately from canonical data. Selecting an alternate never merges recordings or changes listen associations. Unrelated title results are filtered.

Embeddable metadata is not a playback guarantee. The owner confirmed playback worked on the HTTPS test page after local failures; Force of Habit also reached Finished in the observed browser. This demonstrates a working hosted path for that test, not the precise cause of every error 150. **Check player connection** tests cross-origin local Referer delivery; only browser Network headers verify the actual request sent to YouTube.

## Private HTTPS playback

The installed Player has **Open private playback**. It opens https://forgeplayerplayback.famousmoon13.chatgpt.site/ in the default browser, carrying only the selected public YouTube video ID and starting position in the URL fragment. No library, Google token, title or account ID is uploaded. Press Play on the page. If its first login loses the selected song, return to Forge and click Open private playback again after login.

The Site is restricted to its owner, not public or merely unlisted. Other download users cannot access it without an explicit access grant. This is a separate player window, not a proxy or full library deployment: queue advancement, local timestamps and listen-event tracking do not synchronize with it. The downloaded app still starts on localhost and works with the local database independently. YouTube streaming and the private HTTPS page require internet.

## Existing features

Genre topics and explicit artist credits create local mixes. Manual corrections win. Takeout supplies historical play counts, not playback permission. Likes API limits remain; missing results are not unlikes. Favorites retains the rolling 90-day rule and overrides. YouTube publishing still requires its own permission, preview and approval. One YouTube channel per library is supported; a different account requires disconnect, and a separate data folder is appropriate for an entirely separate library.

## Release evidence

See CHANGELOG-v050.md, MIGRATION-v050.md, HOSTING-v050.md, VERIFICATION-v050.md and PRIVACY-DRAFT.md. Tests: `python -m unittest discover -s tests -v`; `node tests/test_player.cjs`. They use fixtures/mocks, not destructive live-account tests.

The Desktop `client_secret` field in app_oauth.json is public-client configuration required by Google's exchange, not a confidential hosted Web-client secret. User access/refresh tokens must never be distributed. The loopback app is for a trusted Windows user; do not expose it through port forwarding or a public tunnel. No public GitHub push or full-library deployment has been performed.
