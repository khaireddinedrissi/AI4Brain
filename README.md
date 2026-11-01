# AI4Brain

## Run locally (Windows PowerShell)

Use Python 3.11 or newer.

### Quick start

Double-click `run.bat`. It creates the local virtual environment, installs or
updates the requirements, and starts the server. Open <http://127.0.0.1:5000>
in your browser. Keep the command window open while using the app; press
**Ctrl+C** there to stop the server. A Groq key is optional because Brino has
built-in rule-based guidance when the generative coach is not configured.

### Manual setup

1. Open PowerShell in this folder.
2. Create and activate a virtual environment (recommended):

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install the dependencies and start the server:

   ```powershell
   py -m pip install -r requirements.txt
   py react.py
   ```

4. Open <http://127.0.0.1:5000>.

The Groq-powered coach is optional. Without a key, Brino uses built-in rule-based
guidance; games, scores, and adaptive plans still work. To enable generative
coach replies locally, copy the example and add your own key:

```powershell
Copy-Item .streamlit/secrets.toml.example .streamlit/secrets.toml
```

Replace the placeholder in `.streamlit/secrets.toml` with your key. Never commit
that real secrets file; it is ignored by Git. The safe example file can be
committed. The app reads this TOML file directly and does not need Streamlit
installed. On a hosted demo, set `GROQ_API_KEY` in the host's private environment
settings.

SQLite databases initialize when the first API request arrives; the static home
page can load even when SQLite is unavailable.
Account owners can delete their account and saved data from **My Journey > Privacy
and data controls** after confirming their password. Expired user data is cleaned
up at most once per day when the server receives a request, using the configured
retention period (365 days by default).
