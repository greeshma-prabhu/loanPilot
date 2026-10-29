"""Shared Streamlit page objects for navigation and in-app page switching."""

import streamlit as st

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

OPERATE_PAGES = {
    "overview": st.Page(overview.render, title="Overview", url_path="overview", default=True),
    "applications": st.Page(
        applications.render, title="Applications", url_path="applications"
    ),
    "new_application": st.Page(
        new_application.render, title="New Application", url_path="new-application"
    ),
    "ai_assessment": st.Page(
        ai_assessment.render, title="AI Assessment", url_path="ai-assessment"
    ),
    "human_review": st.Page(
        human_review.render, title="Human Review", url_path="human-review"
    ),
}

KNOW_MORE_PAGES = {
    "approach_story": st.Page(
        approach_story.render, title="Approach Story", url_path="approach-story"
    ),
    "technical_architecture": st.Page(
        technical_architecture.render,
        title="Technical Architecture",
        url_path="technical-architecture",
    ),
    "data_explorer": st.Page(
        data_explorer.render, title="Data Explorer", url_path="data-explorer"
    ),
    "about_faq": st.Page(
        about_faq.render, title="About & FAQ", url_path="about-faq"
    ),
}

REFERENCE_PAGES = {
    "about_faq": st.Page(
        about_faq.render, title="About & FAQ", url_path="about-faq"
    )
}

NAVIGATION = {
    "Operate": list(OPERATE_PAGES.values()),
    "Know more": list(KNOW_MORE_PAGES.values()),
}
