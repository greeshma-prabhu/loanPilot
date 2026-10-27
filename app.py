"""LoanPilot Streamlit application entry point."""

import streamlit as st

from loanpilot import config
from loanpilot.badges import render_badge_legend
from loanpilot.data.seed import seed_demo_data
from loanpilot.data.schema import create_schema
from loanpilot.data.store import SQLiteStore
from loanpilot.navigation import NAVIGATION


def main() -> None:
    """Configure navigation and render the selected page."""
    st.set_page_config(page_title=config.APP_NAME, page_icon="🏦", layout="wide")
    create_schema(SQLiteStore())

    navigation = st.navigation(NAVIGATION)

    with st.sidebar:
        st.markdown(f"## {config.APP_NAME}")
        st.caption(config.BANK_NAME)
        if st.button("Reset demo data", width="stretch"):
            counts = seed_demo_data(SQLiteStore(), reset=True)
            count_text = ", ".join(
                f"{table}: {count}" for table, count in counts.items()
            )
            st.toast(f"Demo data reset. {count_text}")
        st.divider()
        render_badge_legend()

    navigation.run()


if __name__ == "__main__":
    main()
