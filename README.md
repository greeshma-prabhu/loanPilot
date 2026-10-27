# LoanPilot: Agentic Personal Loan Approval

A Streamlit presales point-of-view demo for Aarambh Bank. It uses synthetic
customer data and illustrative policy only; it is not a real bank system or
credit decision.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

The app starts with an empty local SQLite database. Use **Load demo data** on a
page or **Reset demo data** in the sidebar to generate the deterministic
synthetic dataset and sample PDFs. The database lives at `data/loanpilot.db`;
all demo identities and documents are synthetic and are not credit decisions.

Generate or replace the dataset from the command line with
`python -m loanpilot.data.seed --reset`.

The AI Assessment page runs deterministic policy checks and hands every
recommendation to Human Review. Without a `GEMINI_API_KEY`, language output uses
the recorded persona traces; set the key in `.streamlit/secrets.toml` or the
environment to enable Live Gemini. Export replay data created by live assessments
with `python -m loanpilot.agent.record`.

Run the test suite with `pytest`.
