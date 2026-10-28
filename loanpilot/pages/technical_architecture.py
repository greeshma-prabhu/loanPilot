"""Plain-English implementation and target-state architecture."""

import streamlit as st

from loanpilot.ledger import ledger_frame
from loanpilot.theme import render_disclaimer, render_header


def _architecture_diagram() -> None:
    """Draw the logical architecture using labelled, status-coloured nodes."""
    dot = r"""
    digraph architecture {
      graph [rankdir=TB, bgcolor="transparent", pad="0.2", nodesep="0.32", ranksep="0.5"];
      node [shape=box, style="rounded,filled", fontname="Arial", fontsize=10,
            color="#b9c9c7", fontcolor="#163d3c", margin="0.13,0.09"];
      edge [color="#75928f", penwidth=1.35, arrowsize=0.65];
      sources [label="Sources\nCore banking · documents\nBureau mock · KYC mock · policy docs", fillcolor="#fff0cf"];
      ingest [label="Ingestion\nGuided intake · PDF reading\nSeed / simulator", fillcolor="#d9f0e2"];
      subgraph cluster_lake {
        label="Enterprise data platform"; style="rounded"; color="#d7e2e1";
        raw [label="RAW\nas received", fillcolor="#e8f4f2"];
        curated [label="CURATED\ncleaned and joined", fillcolor="#d9f0e2"];
        serving [label="SERVING\ndecision features", fillcolor="#d9f0e2"];
        bigquery [label="BigQuery\nPlanned", fillcolor="#eceff1"];
        raw -> curated -> serving;
      }
      feature [label="Feature and\npolicy layer\nPython rules", fillcolor="#d9f0e2"];
      runner [label="Agent runner\n5-step orchestrator", fillcolor="#d9f0e2"];
      toolbox [label="Tool box\nextraction · bureau · KYC\npolicy · rules · pricing", fillcolor="#fff0cf"];
      ui [label="Application UI\nand human review", fillcolor="#d9f0e2"];
      audit [label="Audit and\nobservability\nSQLite trace + audit log", fillcolor="#d9f0e2"];
      sources -> ingest -> raw;
      serving -> feature -> runner;
      runner -> toolbox;
      toolbox -> serving [style=dashed];
      runner -> ui -> audit;
      curated -> bigquery [style=dashed];
      bigquery -> feature [style=dashed];
    }
    """
    st.graphviz_chart(dot, width="stretch")
    st.caption(
        "Green = Real in this demo · Amber = Simulated · Grey = Planned. "
        "Each node also names its status."
    )


def render() -> None:
    """Render architecture, data flow, tools, governance, and target mapping."""
    render_disclaimer()
    render_header(
        "Technical Architecture",
        "How the demo pieces fit together, where information moves, and what is real today.",
        "EXPLAIN  /  D3 ARCHITECTURE",
    )
    statuses = ledger_frame().set_index("component")["status"].to_dict()
    gemini_status = statuses.get("Gemini extraction and explanation", "Simulated")
    tabs = st.tabs(
        [
            "Layers",
            "Technology",
            "Agents and tools",
            "Data flow",
            "Governance",
            "Reference mapping",
            "Built vs target",
        ]
    )
    with tabs[0]:
        _architecture_diagram()
        st.subheader("What each layer does")
        st.dataframe(
            [
                {"Layer": "Sources", "Purpose": "Synthetic account facts, PDFs, mock bureau/KYC responses and policy documents."},
                {"Layer": "Ingestion", "Purpose": "Guided intake stores submitted fields and registered document evidence."},
                {"Layer": "Lakehouse", "Purpose": "RAW keeps received data; CURATED joins it; SERVING exposes decision features."},
                {"Layer": "Feature and policy", "Purpose": "Builds ratios and applies deterministic policy rules."},
                {"Layer": "Agent orchestrator", "Purpose": "Runs five ordered steps and records tool calls; it cannot sanction."},
                {"Layer": "Application and human review", "Purpose": "Shows the case, evidence and recommendation for a human decision."},
                {"Layer": "Audit and observability", "Purpose": "Stores step traces, decisions and audit events for later review."},
            ],
            width="stretch",
            hide_index=True,
        )
    with tabs[1]:
        st.subheader("Technology in this demo")
        st.dataframe(
            [
                {"Technology": "Streamlit", "Role": "Multipage application and review interface.", "Status": "Real"},
                {"Technology": "Python", "Role": "Deterministic policy, calculations and orchestration.", "Status": "Real"},
                {"Technology": "SQLite", "Role": "Local stand-in with the demo schema.", "Status": "Real"},
                {"Technology": "Gemini", "Role": "Optional document extraction and explanation only.", "Status": gemini_status},
                {"Technology": "BigQuery", "Role": "Possible enterprise data platform target.", "Status": "Planned"},
            ],
            width="stretch",
            hide_index=True,
        )
    with tabs[2]:
        st.subheader("Agent and tool inventory")
        st.dataframe(
            [
                {"Name": "Document Verification Agent", "Role": "Extract fields and reconcile evidence.", "Inputs": "PDF text, applicant record", "Outputs": "Fields, snippets, flags", "Status": "Real"},
                {"Name": "Financial Assessment Agent", "Role": "Calculate income burden and affordability.", "Inputs": "Income, EMIs, amount, term", "Outputs": "EMI, FOIR", "Status": "Real"},
                {"Name": "Credit & Policy Agent", "Role": "Check credit and policy clauses.", "Inputs": "Bureau/KYC response, features", "Outputs": "Clause results", "Status": "Real"},
                {"Name": "Risk Assessment Agent", "Role": "Summarize deterministic risk flags.", "Inputs": "Score, file depth, document results", "Outputs": "Risk band", "Status": "Real"},
                {"Name": "Recommendation Agent", "Role": "Prepare a recommendation and handoff.", "Inputs": "Policy and financial results", "Outputs": "Approve / Refer / Decline and reasons", "Status": "Real"},
                {"Name": "Document extraction", "Role": "Read evidence text and flag discrepancies.", "Inputs": "Synthetic PDF", "Outputs": "Fields and evidence flags", "Status": gemini_status},
                {"Name": "Bureau and KYC simulators", "Role": "Provide synthetic external-response shapes.", "Inputs": "Synthetic application", "Outputs": "Mock response payloads", "Status": "Simulated"},
                {"Name": "Policy, rules and pricing", "Role": "Apply deterministic checks and rate grid.", "Inputs": "Features and policy clauses", "Outputs": "Clause results and price", "Status": "Real"},
            ],
            width="stretch",
            hide_index=True,
        )
    with tabs[3]:
        st.subheader("Data flow in five steps")
        for step in (
            "1. Intake saves an application and its synthetic or uploaded documents.",
            "2. RAW records preserve evidence and mock service responses.",
            "3. CURATED and SERVING join records and calculate decision features.",
            "4. The orchestrator calls tools and deterministic policy code in five steps.",
            "5. A human reviews the recommendation; actions and handoffs are audited.",
        ):
            st.write(step)
    with tabs[4]:
        st.subheader("Governance and privacy")
        st.markdown(
            "- Human-in-the-loop: a person decides before sanction; AI cannot approve a sanction.\n"
            "- Audit: steps, tool outputs, reviewer action and written override reasons are recorded.\n"
            "- PII stance: this demo uses synthetic people and fake `DEMO…` identifiers only. "
            "Uploaded files should also be synthetic.\n"
            "- Gemini: wording or extraction cannot override deterministic policy results."
        )
    with tabs[5]:
        st.subheader("Brief reference layers")
        st.dataframe(
            [
                {"Reference layer": "Agent runner", "LoanPilot component": "Five-step deterministic orchestrator and persisted trace."},
                {"Reference layer": "Tool box", "LoanPilot component": "Document extraction, reconciliation, bureau/KYC checks, policy, rules and pricing tools."},
                {"Reference layer": "Session and memory", "LoanPilot component": "Streamlit session state, SQLite assessment traces and per-step LLM cache."},
                {"Reference layer": "Enterprise data platform", "LoanPilot component": "RAW/CURATED/SERVING schema; local SQLite stand-in, BigQuery planned."},
                {"Reference layer": "Human-in-the-loop", "LoanPilot component": "Human Review queue, decision reasons, overrides and sanction gate."},
            ],
            width="stretch",
            hide_index=True,
        )
    with tabs[6]:
        st.subheader("Built versus target state")
        st.dataframe(ledger_frame(), width="stretch", hide_index=True)
