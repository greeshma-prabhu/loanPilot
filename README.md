# LoanPilot: Agentic Personal Loan Approval

A Streamlit presales point-of-view demo for Aarambh Bank. This shell contains
placeholder pages only and uses no real customer data or credit decisions.

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

Run the test suite with `pytest`.
