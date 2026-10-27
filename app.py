"""LoanPilot Streamlit application entry point."""

import streamlit as st

from loanpilot import config
from loanpilot.badges import render_badge_legend
from loanpilot.pages import (
    about_faq,
    ai_assessment,
    applications,
    approach_story,
    data_explorer,
    human_review,
    new_application,
    overview,
    technical_architecture,
)


def main() -> None:
    """Configure navigation and render the selected page."""
    st.set_page_config(page_title=config.APP_NAME, page_icon="🏦", layout="wide")

    navigation = st.navigation(
        {
            "Operate": [
                st.Page(overview.render, title="Overview", url_path="overview", default=True),
                st.Page(applications.render, title="Applications", url_path="applications"),
                st.Page(
                    new_application.render,
                    title="New Application",
                    url_path="new-application",
                ),
                st.Page(ai_assessment.render, title="AI Assessment", url_path="ai-assessment"),
                st.Page(human_review.render, title="Human Review", url_path="human-review"),
            ],
            "Explain": [
                st.Page(approach_story.render, title="Approach Story", url_path="approach-story"),
                st.Page(
                    technical_architecture.render,
                    title="Technical Architecture",
                    url_path="technical-architecture",
                ),
                st.Page(data_explorer.render, title="Data Explorer", url_path="data-explorer"),
            ],
            "Reference": [
                st.Page(about_faq.render, title="About & FAQ", url_path="about-faq")
            ],
        }
    )

    with st.sidebar:
        st.markdown(f"## {config.APP_NAME}")
        st.caption(config.BANK_NAME)
        if st.button("Reset demo data", width="stretch"):
            st.toast("Reset arrives in phase 2")
        st.divider()
        render_badge_legend()

    navigation.run()


if __name__ == "__main__":
    main()
