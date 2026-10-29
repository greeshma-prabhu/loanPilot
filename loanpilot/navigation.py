"""Shared Streamlit page definitions for navigation and in-app page switching."""

import streamlit as st

from loanpilot.pages import (
    about_faq,
    ai_assessment,
    applications,
    approach_story,
    data_explorer,
    document_library,
    guided_demo,
    human_review,
    new_application,
    overview,
    technical_architecture,
)

def _create_page_maps():
    """Create new Page instances for one execution of the Streamlit entrypoint."""
    operate_pages = {
        "overview": st.Page(
            overview.render, title="Overview", url_path="overview", default=True
        ),
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
        "document_library": st.Page(
            document_library.render,
            title="Document Library",
            url_path="document-library",
        ),
        "guided_demo": st.Page(
            guided_demo.render,
            title="Guided Demo",
            url_path="guided-demo",
        ),
    }
    know_more_pages = {
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
    reference_pages = {
        "about_faq": st.Page(
            about_faq.render, title="About & FAQ", url_path="about-faq"
        )
    }
    navigation = {
        "Operate": list(operate_pages.values()),
        "Know more": list(know_more_pages.values()),
    }
    return operate_pages, know_more_pages, reference_pages, navigation


OPERATE_PAGES, KNOW_MORE_PAGES, REFERENCE_PAGES, NAVIGATION = _create_page_maps()


def build_navigation():
    """Refresh page objects so no st.Page instance is run twice across reruns."""
    global OPERATE_PAGES, KNOW_MORE_PAGES, REFERENCE_PAGES, NAVIGATION
    (
        OPERATE_PAGES,
        KNOW_MORE_PAGES,
        REFERENCE_PAGES,
        NAVIGATION,
    ) = _create_page_maps()
    return OPERATE_PAGES, KNOW_MORE_PAGES, NAVIGATION
