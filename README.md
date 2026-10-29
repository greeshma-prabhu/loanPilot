# LoanPilot: Agentic Personal Loan Approval

A Streamlit presales demonstration for fictional Aarambh Bank. LoanPilot uses
synthetic people, documents, and bureau/KYC responses. It is not a real bank
system, credit decision, loan offer, or regulatory-compliance claim. AI can
recommend and explain, but a human reviewer makes the decision.

The workspace includes demo-grade sign-in. Credentials and demo access are
configured through `.streamlit/secrets.toml` or the supported local environment
variables. Generate password hashes with `python -m loanpilot.auth.make_hash`.
Sign-in persists across page refreshes for up to 7 days or until sign out. Set
`auth.session_secret` (or `LOANPILOT_AUTH_SESSION_SECRET`) to a long random
secret for stable sessions across app restarts and multiple instances. Sign-in
has no MFA or single sign-on.

Demonstration with synthetic data. Not a real bank system or credit decision.

## Run locally

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

### Linux or macOS

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

On first launch the app creates the local SQLite database and synthetic sample
documents if they are missing. The application paths are rooted at the project
directory, so the launch command can also name `app.py` by its full path from
another working directory.

### Optional Gemini language output

The app works without credentials and uses clearly labelled recorded output.
For local development, copy `.streamlit/secrets.toml.example` to
`.streamlit/secrets.toml` and add a Gemini API key:

Windows PowerShell:

```powershell
Copy-Item .streamlit\secrets.toml.example .streamlit\secrets.toml
notepad .streamlit\secrets.toml
```

Linux or macOS:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
${EDITOR:-nano} .streamlit/secrets.toml
```

Then put the key in the file:

```toml
GEMINI_API_KEY = "your-key"
```

Alternatively, set the key in the environment for the current terminal:

```powershell
$env:GEMINI_API_KEY = "your-key"
```

```bash
export GEMINI_API_KEY="your-key"
```

Never commit the key. To override the default `gemini-2.5-flash` model, set
`GEMINI_MODEL` in the environment using the same syntax. Gemini only extracts
fields and writes explanations; it cannot change deterministic policy outcomes
or sanction a loan.

## Deploy to Streamlit Community Cloud

1. Push this repository to a GitHub repository accessible to your Streamlit
   Community Cloud account. Do not include `.streamlit/secrets.toml` or local
   database files.
2. In Streamlit Community Cloud, choose **Create app**, select the repository,
   branch, and `app.py` as the main file, then deploy.
3. Optional: open the app's **Settings → Secrets**, add:

   ```toml
   GEMINI_API_KEY = "your-key"
   ```

   With no key, the app continues in recorded mode. Do not paste credentials
   into code, logs, or this repository.
4. Community Cloud installs dependencies from `requirements.txt`. At startup
   the app creates the SQLite database and synthetic documents if absent.
   Local files on hosted app instances are ephemeral; expect demo data to be
   regenerated after a host restart.

The personas, generated PDFs, and all sample responses are synthetic. Gemini is
optional and is not required for deployment.

## Reset demo data

Reset replaces the local demo database and regenerates its synthetic sample
documents. It does not erase source code or Streamlit secrets.

### Windows PowerShell

```powershell
.\.venv\Scripts\python.exe -m loanpilot.data.seed --reset
```

### Linux or macOS

```bash
.venv/bin/python -m loanpilot.data.seed --reset
```

The **Reset demo data** sidebar button performs the same synthetic-data reset.

## Tests

From a clean clone, create and activate the environment using the commands
above, then run:

```bash
python -m pytest
```

The suite covers all nine page renders, workflows, bootstrap behavior, and
style checks. Tests use temporary databases where writes are required.

## Project structure

```text
app.py                      Streamlit entry point and navigation
loanpilot/
  agent/                    Assessment, language wrapper, and sanction workflows
  data/                     SQLite schema, queries, bootstrap, and seed data
  pages/                    The nine Streamlit pages
  policy/                   Illustrative deterministic policy configuration
  config.py                 Project-root paths and application settings
  theme.py                  Shared page styling and presentation helpers
data/                       Local database and generated synthetic PDFs
docs/                       Research notes and AI usage log
tests/                      Workflow, page-load, and style tests
.streamlit/                 Streamlit theme and secrets example
requirements.txt            Runtime and test dependencies
```
