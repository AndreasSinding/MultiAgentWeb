# ui/streamlit_app.py  (LOCAL USE ONLY)
import os
import json
import requests
import streamlit as st

FASTAPI_URL = os.getenv("FASTAPI_URL", "http://127.0.0.1:8787")

def call_crewai(topic: str):
    resp = requests.post(f"{FASTAPI_URL}/run", json={"topic": topic}, timeout=120)
    resp.raise_for_status()
    return resp.json()

from .ppt_builder import create_multislide_pptx  # reuse backend-safe builder

st.set_page_config(page_title="MultiAgent UI", layout="centered")
st.title("🤖 MultiAgent – Report Generator")
st.subheader("Welcome to the MultiAgent! Please insert your research topic.")

topic = st.text_input("Research Topic", placeholder="e.g., Outlook for AI market in Nordic region 2026")

if st.button("Generate Report"):
    if not topic.strip():
        st.warning("Please enter a topic.")
    else:
        st.write(f"Using backend URL: {FASTAPI_URL}")
        with st.spinner("Running MultiAgent analysis..."):
            result = call_crewai(topic)

        st.success("Analysis complete!")
        with st.expander("Show raw JSON result"):
            st.json(result)

        file_path = create_multislide_pptx(result, topic)

        with open(file_path, "rb") as f:
            st.download_button(
                label="⬇ Download PowerPoint Report",
                data=f,
                file_name=os.path.basename(file_path),
                mime="application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
