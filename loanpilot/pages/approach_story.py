"""Business-first story for LoanPilot's data and assisted decision journey."""

import json
import streamlit as st

from loanpilot import config
from loanpilot.theme import render_disclaimer, render_header

def _render_research_basis() -> None:
    """Direct readers to the consolidated research note section."""
    st.caption("See About & FAQ, Research note.")


def _render_lakehouse_diagram() -> None:
    """Show separate source silos converging into the three governed data layers."""
    dot = r"""
    digraph lakehouse {
      graph [rankdir=LR, bgcolor="transparent", pad="0.2", nodesep="0.35", ranksep="0.55"];
      node [shape=box, style="rounded,filled", fontname="Arial", fontsize=11, color="#b9c9c7", fontcolor="#163d3c", margin="0.16,0.10"];
      edge [color="#75928f", penwidth=1.5, arrowsize=0.7];
      core [label="Core banking\ndatabase", fillcolor="#f5f8f8"];
      docs [label="Scanned\ndocuments", fillcolor="#f5f8f8"];
      bureau [label="Credit bureau\nservice", fillcolor="#fff0cf"];
      kyc [label="KYC\nservice", fillcolor="#fff0cf"];
      policy [label="Policy\nPDFs", fillcolor="#f5f8f8"];
      raw [label="RAW\nAs received", fillcolor="#e8f4f2"];
      curated [label="CURATED\nCleaned and joined", fillcolor="#d9f0e2"];
      serving [label="SERVING\nDecision-ready features", fillcolor="#d9f0e2"];
      core -> raw; docs -> raw; bureau -> raw; kyc -> raw; policy -> raw;
      raw -> curated -> serving;
    }
    """
    st.graphviz_chart(dot, width="stretch")
    st.caption("Legend: Green = Real in this demo · Amber = Simulated source · Grey = Planned state.")


def _render_journey_diagram() -> None:
    """Compare stacked manual and agent-assisted journeys with clear decision points."""
    st.markdown("#### TO-BE · Agent support with a human decision")
    to_be = r"""
    digraph to_be {
      graph [rankdir=LR, bgcolor="transparent", pad="0.16", nodesep="0.2", ranksep="0.3"];
      node [shape=box, style="rounded,filled", fontname="Arial", fontsize=14,
            color="#bccdcb", fontcolor="#173d3c", margin="0.12,0.09"];
      edge [color="#718b89", penwidth=1.3, arrowsize=0.65];
      subgraph cluster_to_applicant {
        label="Applicant"; style="rounded"; color="#dce8e7";
        app [label="Application", fillcolor="#e8f4f2"];
      }
      subgraph cluster_to_channel {
        label="Branch or digital channel"; style="rounded"; color="#dce8e7";
        docs [label="Document verification\nAgent organizes evidence", fillcolor="#d9f0e2"];
      }
      subgraph cluster_to_agent {
        label="Agent"; style="rounded"; color="#b8d9d1";
        finances [label="Financial assessment\nAgent calculates", fillcolor="#d9f0e2"];
        policy [label="Credit and policy\nAgent checks rules", fillcolor="#d9f0e2"];
        risk [label="Risk\nAgent summarizes", fillcolor="#d9f0e2"];
      }
      subgraph cluster_to_credit {
        label="Credit officer"; style="rounded"; color="#dce8e7";
        decision [label="Human decision\nMust be decided by a person", fillcolor="#d9f0e2", penwidth=2, color="#23866f"];
      }
      subgraph cluster_to_operations {
        label="Operations"; style="rounded"; color="#dce8e7";
        sanction [label="Sanction\nAfter human approval", fillcolor="#eceff1"];
        disbursement [label="Disbursement\nSimulated in demo", fillcolor="#fff0cf"];
      }
      app -> docs -> finances -> policy -> risk -> decision -> sanction -> disbursement;
    }
    """
    st.graphviz_chart(to_be, width="stretch")
    st.markdown("#### AS-IS · Manual handoffs")
    as_is = r"""
    digraph as_is {
      graph [rankdir=LR, bgcolor="transparent", pad="0.16", nodesep="0.2", ranksep="0.3"];
      node [shape=box, style="rounded,filled", fontname="Arial", fontsize=14,
            color="#bccdcb", fontcolor="#173d3c", margin="0.12,0.09"];
      edge [color="#718b89", penwidth=1.3, arrowsize=0.65];
      subgraph cluster_as_applicant {
        label="Applicant"; style="rounded"; color="#dce8e7";
        app [label="Application", fillcolor="#eceff1"];
      }
      subgraph cluster_as_channel {
        label="Branch or digital channel"; style="rounded"; color="#dce8e7";
        docs [label="Document verification", fillcolor="#eceff1"];
      }
      subgraph cluster_as_analyst {
        label="Credit analyst (manual)"; style="rounded"; color="#dce8e7";
        finances [label="Financial assessment", fillcolor="#eceff1"];
        policy [label="Credit and policy", fillcolor="#eceff1"];
        risk [label="Risk", fillcolor="#eceff1"];
      }
      subgraph cluster_as_officer {
        label="Credit officer"; style="rounded"; color="#dce8e7";
        decision [label="Human decision", fillcolor="#eceff1"];
      }
      subgraph cluster_as_operations {
        label="Operations"; style="rounded"; color="#dce8e7";
        sanction [label="Sanction", fillcolor="#eceff1"];
        disbursement [label="Disbursement", fillcolor="#eceff1"];
      }
      app -> docs -> finances -> policy -> risk -> decision -> sanction -> disbursement;
    }
    """
    st.graphviz_chart(as_is, width="stretch")
    st.caption(
        "TO-BE lanes: Applicant; Branch or digital channel; Agent; Credit officer; "
        "Operations. AS-IS lanes: Applicant; Branch or digital channel; Credit "
        "analyst (manual); Credit officer; Operations. Green = Real, amber = "
        "Simulated, grey = Planned or manual; labels state each status."
    )


def render() -> None:
    """Render the two-act lakehouse and human-led agent story."""
    render_disclaimer()
    render_header(
        "Approach Story",
        "A plain-English view of how better data and bounded automation can support personal-loan decisions.",
        "EXPLAIN  /  D2 APPROACH",
    )
    st.markdown("## Act 1 · Lakehouse first")
    st.markdown("### Today's picture: useful information is split across silos")
    st.write(
        "Customer records sit in a core banking database. Documents arrive as scans. "
        "Bureau and KYC information comes from separate services. Credit rules live "
        "in policy PDFs. Officers must bring these pieces together by hand."
    )
    st.markdown("### The answer: one governed lakehouse")
    st.write(
        "A lakehouse is a shared data foundation. It keeps original evidence, prepares "
        "clean joined records, and serves the features needed for a decision."
    )
    _render_lakehouse_diagram()
    outcomes = st.columns(4, gap="large")
    for column, title, detail in zip(
        outcomes,
        (
            "One applicant view",
            "Consistent evidence",
            "Searchable rules",
            "Full audit trail",
        ),
        (
            "Bring account, income and case information together.",
            "Give every credit officer the same prepared facts.",
            "Find policy clauses and document evidence in one place.",
            "Record what was checked, changed and decided.",
        ),
        strict=True,
    ):
        with column:
            with st.container(border=True):
                st.markdown(f"#### {title}")
                st.write(detail)

    st.divider()
    st.markdown("## Act 2 · Agents on top, humans decide")
    st.markdown("### A clearer journey with a clear human decision point")
    st.write(
        "The agent can organize evidence, calculate affordability and apply coded "
        "policy rules. A credit officer still makes the decision. In this demo, "
        "disbursement is simulated."
    )
    _render_journey_diagram()
    st.markdown("### Guardrails")
    guardrails = st.columns(4, gap="large")
    for column, title, explanation in zip(
        guardrails,
        ("Policy as code", "No AI sanction", "Reasons for overrides", "Audit log"),
        (
            "Rules run in deterministic code and can be reviewed.",
            "The agent recommends; a person must approve a sanction.",
            "A different human decision needs a written reason.",
            "Steps and decisions leave a trace for review.",
        ),
        strict=True,
    ):
        with column:
            st.markdown(f"**{title}**")
            st.caption(explanation)
    st.markdown("### Three-step roadmap")
    roadmap = st.columns(3, gap="large")
    roadmap_items = (
        ("1 · Assist", "Help officers organize evidence and apply policy consistently."),
        ("2 · Sample", "Consider partial straight-through handling for clean cases, with human sampling and controls."),
        ("3 · Scale", "Extend to more loan products after governance and outcomes are proven."),
    )
    for column, (title, text) in zip(roadmap, roadmap_items, strict=True):
        with column:
            with st.container(border=True):
                st.markdown(f"#### {title}")
                st.write(text)

    st.divider()
    st.markdown("## Close · Benefits, risks and mitigations")
    st.dataframe(
        [
            {
                "Potential benefit": "Less time spent collecting the same evidence",
                "Risk to manage": "Incorrect or incomplete source records",
                "Mitigation": "Show source evidence, flag missing items, keep a human reviewer.",
            },
            {
                "Potential benefit": "More consistent policy checks",
                "Risk to manage": "Rules or data may encode unfair outcomes",
                "Mitigation": "Review policy, monitor outcomes, test across customer groups.",
            },
            {
                "Potential benefit": "Clearer case history",
                "Risk to manage": "Sensitive personal information",
                "Mitigation": "Use synthetic data here; apply access and retention controls in production.",
            },
        ],
        width="stretch",
        hide_index=True,
    )
    _render_research_basis()
    with config.ILLUSTRATIVE_METRICS_PATH.open(encoding="utf-8") as metrics_file:
        metrics = json.load(metrics_file)
    st.caption(
        "Illustrative turnaround assumptions only — "
        f"baseline {metrics['baseline_turnaround_days']:g} days, "
        f"demo {metrics['demo_turnaround_days']:g} days. "
        f"{metrics['source']}"
    )
