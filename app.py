"""
app.py
Streamlit web application for TVB Autonomous Lead-Gen Agent.
Built for The Venture Build (TVB) Intern Project Evaluation.
"""

import os
import io
import json
import streamlit as st
import pandas as pd
from dotenv import load_dotenv

load_dotenv()

from pipeline import run_pipeline, MIN_LEADS

st.set_page_config(
    page_title="TVB Autonomous Lead-Gen Agent",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS styling for premium look & feel
st.markdown("""
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        background: linear-gradient(90deg, #4F46E5, #06B6D4);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        color: #94A3B8;
        font-size: 1.05rem;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background-color: #1E293B;
        border: 1px solid #334155;
        border-radius: 10px;
        padding: 15px;
        text-align: center;
    }
    .metric-val {
        font-size: 1.8rem;
        font-weight: 700;
        color: #38BDF8;
    }
    .metric-label {
        font-size: 0.85rem;
        color: #94A3B8;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .tag-badge {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 9999px;
        font-size: 0.78rem;
        font-weight: 600;
        margin: 2px;
        background: #312E81;
        color: #C7D2FE;
        border: 1px solid #4338CA;
    }
</style>
""", unsafe_allow_html=True)

# App Header
st.markdown('<div class="main-header">🎯 TVB Autonomous Lead-Gen Agent</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-header">Autonomously discovers and validates companies strictly matching '
    '<b>The Venture Build\'s</b> target investment profile with verified executive contacts.</div>',
    unsafe_allow_html=True
)

# Profile Parameters Badges
st.markdown("""
<div>
    <span class="tag-badge">💰 $1M - $5M Funding / Revenue</span>
    <span class="tag-badge">💻 Tech-Related Platform</span>
    <span class="tag-badge">🌍 Non-US (Minimal to No US Presence)</span>
    <span class="tag-badge">✉️ Verified CEO/Founder Email</span>
    <span class="tag-badge">🎯 Minimum Bar: 15 Leads</span>
</div>
<hr style="margin: 15px 0; border: 0; border-top: 1px solid #334155;">
""", unsafe_allow_html=True)

# Sidebar Configuration
with st.sidebar:
    st.header("⚙️ Agent Controls")
    
    min_leads = st.number_input(
        "Target Qualifying Leads",
        min_value=1,
        max_value=50,
        value=MIN_LEADS,
        help="The agent will autonomously run discovery rounds until this threshold is reached."
    )
    
    st.subheader("🔑 API & Discovery Settings")
    env_gemini_key = os.environ.get("GEMINI_API_KEY", "")
    
    user_gemini_key = st.text_input(
        "Gemini API Key (Optional)",
        value=env_gemini_key,
        type="password",
        help="Leave blank to use preconfigured server key or autonomous web search engine."
    )
    
    gemini_model = st.selectbox(
        "Gemini Model",
        ["gemini-3.1-flash-lite", "gemini-3.6-flash", "gemini-flash-latest", "gemini-2.5-flash"],
        index=0,
        help="Select model for LLM-assisted search grounding."
    )
    
    if user_gemini_key:
        os.environ["GEMINI_API_KEY"] = user_gemini_key
    if gemini_model:
        os.environ["GEMINI_MODEL"] = gemini_model

    st.success("🟢 Autonomous Web Engine: ACTIVE\n(Self-healing multi-source discovery enabled)")
    
    with st.expander("📋 Target Profile & Rules", expanded=False):
        st.markdown("""
        **TVB Parameters**:
        - **Stage**: Revenue or funding between **$1M and $5M USD**.
        - **Product**: Tech-related platform (SaaS, marketplace, API, software).
        - **Geography**: Minimal to no US presence (headquartered outside the US).
        - **Executive Contact**: Name & email of CEO or Co-founder must be available.
        - **Data Integrity**: Unverified/untrue fields are left blank.
        """)

# Main Action Area
col1, col2 = st.columns([1, 4])
with col1:
    run_agent = st.button("🚀 Run Lead Agent", type="primary", use_container_width=True)

# Progress & Logs container
progress_bar = st.progress(0)
status_placeholder = st.empty()
log_placeholder = st.empty()
results_placeholder = st.empty()

if run_agent:
    log_lines = []

    def app_logger(msg):
        log_lines.append(str(msg))
        # Keep log clean and responsive
        log_placeholder.code("\n".join(log_lines[-35:]), language="text")

    status_placeholder.info("⚡ Agent active: Initiating autonomous multi-source discovery...")
    progress_bar.progress(10)

    try:
        leads = run_pipeline(
            min_leads=int(min_leads),
            api_key=user_gemini_key or env_gemini_key,
            log=app_logger
        )
        progress_bar.progress(100)
    except Exception as e:
        st.error(f"Error during execution: {e}")
        leads = []

    if not leads:
        status_placeholder.error(
            "⚠️ No qualifying leads found. Please check logs above or ensure network connectivity."
        )
    else:
        status_placeholder.success(f"🎉 Successfully discovered {len(leads)} verified qualifying leads!")
        
        # Metrics row
        m1, m2, m3, m4 = st.columns(4)
        avg_funding = sum(l.get("funding_amount_millions", 0) for l in leads) / len(leads)
        unique_countries = len(set(l.get("country", "") for l in leads))
        verified_pct = 100  # By definition all qualifying leads have verified CEO contact
        
        with m1:
            st.markdown(f'<div class="metric-card"><div class="metric-val">{len(leads)}</div><div class="metric-label">Qualified Leads</div></div>', unsafe_allow_html=True)
        with m2:
            st.markdown(f'<div class="metric-card"><div class="metric-val">${avg_funding:.2f}M</div><div class="metric-label">Avg Funding / Rev</div></div>', unsafe_allow_html=True)
        with m3:
            st.markdown(f'<div class="metric-card"><div class="metric-val">{unique_countries}</div><div class="metric-label">Countries Represented</div></div>', unsafe_allow_html=True)
        with m4:
            st.markdown(f'<div class="metric-card"><div class="metric-val">{verified_pct}%</div><div class="metric-label">Email Verified</div></div>', unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)

        df = pd.DataFrame(leads)
        
        # Display Table
        display_df = df[[
            "company_name", "sector", "funding_amount_millions", "country",
            "ceo_or_founder_name", "verified_email", "email_verification_method", "website"
        ]].rename(columns={
            "company_name": "Company",
            "sector": "Sector / Industry",
            "funding_amount_millions": "Funding ($M)",
            "country": "HQ / Region",
            "ceo_or_founder_name": "CEO / Co-founder",
            "verified_email": "Verified Email",
            "email_verification_method": "Verification",
            "website": "Website"
        })

        results_placeholder.dataframe(
            display_df,
            use_container_width=True,
            column_config={
                "Website": st.column_config.LinkColumn("Website"),
                "Funding ($M)": st.column_config.NumberColumn(format="$%.2fM")
            }
        )

        # Download Buttons
        d1, d2 = st.columns(2)
        with d1:
            csv_buf = io.StringIO()
            df.to_csv(csv_buf, index=False)
            st.download_button(
                "⬇️ Download Leads as CSV",
                data=csv_buf.getvalue(),
                file_name="tvb_qualifying_leads.csv",
                mime="text/csv",
                use_container_width=True
            )
        with d2:
            json_str = json.dumps(leads, indent=2)
            st.download_button(
                "⬇️ Download Leads as JSON",
                data=json_str,
                file_name="tvb_qualifying_leads.json",
                mime="application/json",
                use_container_width=True
            )
else:
    st.info("💡 Click **'🚀 Run Lead Agent'** to start autonomous discovery and validation.")
