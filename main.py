import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import io
import queue
import threading
import time
import concurrent.futures

from job_scraper import scrape_linkedin_jobs
from resume_processor import extract_resume_text
from matching_engine import analyze_matches
from utils import export_to_csv

st.set_page_config(
    page_title="GenAI Job Matching",
    page_icon="💼",
    layout="wide"
)

class ProgressManager:
    """Manages progress display to prevent duplicates"""
    def __init__(self):
        self.status_placeholder = st.empty()
        self.results_placeholder = st.empty()
        self.lock = threading.Lock()
        self.total_jobs = 0
    
    def update_job_search(self, current_count):
        """Update job count display"""
        with self.lock:
            self.total_jobs = current_count  # Update total_jobs when job count updates
            with self.status_placeholder:
                st.markdown(f"**{current_count} jobs found**")
    
    def update_analysis(self, current_count):  # Removed total_count parameter
        """Update analysis progress"""
        with self.lock:
            with self.results_placeholder:
                if self.total_jobs > 0:
                    st.markdown(f"### Live Results: {current_count} jobs analyzed")
                else:
                    st.markdown("### Live Results: Waiting for jobs to analyze...")
    
    def clear(self):
        """Clear all progress displays"""
        with self.lock:
            self.status_placeholder.empty()
            self.results_placeholder.empty()
            self.total_jobs = 0

class JobProcessor:
    """Handles parallel job processing"""
    def __init__(self, resume_text, progress_mgr, results_container):
        self.resume_text = resume_text
        self.progress_mgr = progress_mgr
        self.results_container = results_container
        self.analyzed_jobs = []
        self.lock = threading.Lock()
        self.search_count = 0
        self.analysis_count = 0
        self.should_stop = False
        self.live_results_placeholder = st.empty()

    def display_live_results(self):
        """Display live results in a single location"""
        # Clear the previous results
        self.live_results_placeholder.empty()
        
        # Show new results in the placeholder
        with self.live_results_placeholder.container():
            if st.session_state.top_matches:
                st.markdown("### Live Results")
                for idx, job in enumerate(st.session_state.top_matches, 1):
                    with st.expander(
                        f"#{idx}: {job['title']} at {job['company']} - Match Score: {job['match_score']}%",
                        expanded=True
                    ):
                        col1, col2 = st.columns([2, 1])
                        with col1:
                            st.write("**Company:** ", job['company'])
                            st.write("**Location:** ", job['location'])
                            st.write("**Posted:** ", job['posted_date'])
                            if job['url']:
                                st.write(f"**[Apply Here]({job['url']})**")
                        with col2:
                            st.metric(
                                label="Match Score",
                                value=f"{job['match_score']}%"
                            )
                        st.write("**Match Analysis:**")
                        st.write(job['match_reasoning'])

    def handle_analyzed_job(self, job_with_match):
        """Handle each analyzed job"""
        with self.lock:
            self.analyzed_jobs.append(job_with_match)
            self.analysis_count += 1
            
            # Sort and get top matches
            sorted_jobs = sorted(
                self.analyzed_jobs,
                key=lambda x: x.get('match_score', 0),
                reverse=True
            )
            
            # Update session state
            st.session_state.top_matches = sorted_jobs[:5]
            
            # Update progress - removed total_count parameter
            self.progress_mgr.update_analysis(self.analysis_count)
            
            # Update live results display
            self.display_live_results()
            
    def process_jobs(self, location, distance, role, days, included_companies="", excluded_companies=""):
        """Process jobs and display results in real-time"""
        try:
            # Clear any existing results
            self.live_results_placeholder.empty()

            # Reset counters
            self.search_count = 0
            self.analysis_count = 0
            
            # Process jobs
            for job in scrape_linkedin_jobs(
                location=location,
                distance=distance,
                role=role,
                days=days,
                progress_callback=None,  # Disable the progress callback
                stream_jobs=True,
                included_companies=included_companies,
                excluded_companies=excluded_companies
            ):
                if job:
                    # Update search count first
                    with self.lock:
                        self.search_count += 1
                        self.progress_mgr.update_job_search(self.search_count)
                    
                    # Analyze job and update display
                    analyzed_job = analyze_matches(
                        self.resume_text,
                        [job],
                        progress_callback=None
                    )[0]
                    
                    # Handle the analyzed job
                    self.handle_analyzed_job(analyzed_job)

            return self.analyzed_jobs if self.analyzed_jobs else []

        except Exception as e:
            st.error(f"Error in job processing: {str(e)}")
            return []
        finally:
            # Clear progress displays when done
            self.progress_mgr.clear()

    def _update_search_progress(self, count):
        """Update search progress with thread safety"""
        with self.lock:
            self.search_count = count
            self.progress_mgr.update_job_search(count)

def initialize_session_state():
    """Initialize session state variables"""
    if 'analysis_complete' not in st.session_state:
        st.session_state.analysis_complete = False
    if 'analyzed_jobs' not in st.session_state:
        st.session_state.analyzed_jobs = []
    if 'total_jobs' not in st.session_state:
        st.session_state.total_jobs = 0
    if 'current_job_number' not in st.session_state:
        st.session_state.current_job_number = 0
    if 'top_matches' not in st.session_state:
        st.session_state.top_matches = []

def display_top_matches(container):
    """Display current top 5 matches"""
    if st.session_state.top_matches:
        container.markdown("### Current Top Matches")
        for idx, job in enumerate(st.session_state.top_matches, 1):
            with container.expander(
                f"#{idx}: {job['title']} at {job['company']} - Match Score: {job['match_score']}%",
                expanded=True
            ):
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.write("**Company:** ", job['company'])
                    st.write("**Location:** ", job['location'])
                    st.write("**Posted:** ", job['posted_date'])
                    if job['url']:
                        st.write(f"**[Apply Here]({job['url']})**")
                with col2:
                    st.metric(
                        label="Match Score",
                        value=f"{job['match_score']}%"
                    )
                st.write("**Match Analysis:**")
                st.write(job['match_reasoning'])

def display_results(container):
    """Display final results after analysis is complete"""
    if 'matched_jobs' in st.session_state and st.session_state.analysis_complete:
        matches_df = pd.DataFrame(st.session_state.matched_jobs)

        container.markdown("### Analysis Summary")
        col1, col2, col3 = container.columns(3)
        with col1:
            st.metric(
                label="Total Jobs Found",
                value=len(matches_df)
            )
        with col2:
            avg_score = matches_df['match_score'].mean()
            st.metric(
                label="Average Match Score",
                value=f"{avg_score:.1f}%"
            )
        with col3:
            high_matches = len(matches_df[matches_df['match_score'] >= 80])
            st.metric(
                label="High Matches (≥80%)",
                value=high_matches
            )

        container.markdown("### All Matches")
        for idx, (_, job) in enumerate(matches_df.iterrows()):
            with container.expander(
                f"{job['title']} at {job['company']} - Match Score: {job['match_score']}%",
                expanded=False
            ):
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.write("**Company:** ", job['company'])
                    st.write("**Location:** ", job['location'])
                    st.write("**Posted:** ", job['posted_date'])
                    if job.get('url'):
                        st.write(f"**[Apply Here]({job['url']})**")
                with col2:
                    st.metric(
                        label="Match Score",
                        value=f"{job['match_score']}%"
                    )
                st.write("**Match Analysis:**")
                st.write(job['match_reasoning'])
                st.write("**Job Description:**")
                st.write(job['description'])

        container.markdown("---")
        container.markdown("### Export Results")
        if container.button("Export to CSV", key="export_button", use_container_width=True):
            csv = export_to_csv(matches_df)
            container.download_button(
                label="Download CSV",
                data=csv,
                file_name=f"job_matches_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                key="download_button",
                use_container_width=True
            )

def main():
    st.markdown("""
    <style>
    /* Reduce top spacing */
    .main .block-container {
        padding-top: 1rem !important;
    }
    
    /* Hide deploy text */
    .stDeployButton {
        display: none !important;
    }
    
    /* Adjust status layout */
    .stStatusWidget {
        display: flex;
        justify-content: flex-end;
        gap: 1rem;
        align-items: center;
    }
    
    /* Better spacing for results */
    .element-container {
        margin-bottom: 0.5rem;
    }
    </style>
""", unsafe_allow_html=True)
    
    display_header()

    initialize_session_state()

    # Create containers for different sections
    progress_mgr = ProgressManager()
    results_container = st.container()
    update_progress_display(progress_mgr)

    with st.sidebar:
        st.header("Search Parameters")
        
        # Full width Job Keywords
        keywords = st.text_input("Job Keywords", "Product Manager", key="keywords_input")
        
        # Location and Distance on same line
        col1, col2 = st.columns([2, 1])
        with col1:
            location = st.text_input("Location", "McLean, VA", key="location_input")
        with col2:
            distance = st.number_input("Distance", 0, 100, 25, key="distance_input", help="Miles")
        
        # Move Posted Date above Company Filters
        time_filter = st.select_slider(
            "Posted Date",
            options=["24h", "Week", "Month", "Any"],
            value="24h",
            key="time_filter"
        )
        
        # Map the simplified options
        time_filter_map = {
            "24h": 1,
            "Week": 7,
            "Month": 30,
            "Any": None
        }
        days_filter = time_filter_map[time_filter]
        
        # Company Filters section
        st.markdown("### Company Filters")
        included_companies = st.text_area(
            "Include Companies",
            placeholder="One company per line",
            height=100,
            key="included_companies"
        )
        
        excluded_companies = st.text_area(
            "Exclude Companies",
            placeholder="One company per line",
            height=100,
            key="excluded_companies"
        )
        
        # Resume section
        st.markdown("### Resume")
        uploaded_file = st.file_uploader(
            "Upload PDF",
            type=['pdf'],
            key="resume_uploader"
        )
        
        search_button = st.button(
            "Find Matches", 
            type="primary", 
            use_container_width=True,
            key="search_button"
        )

    if search_button:
        if not uploaded_file:
            st.error("Please upload your resume first!")
            return

        try:
            # Reset states
            st.session_state.analysis_complete = False
            st.session_state.analyzed_jobs = []
            st.session_state.current_job_number = 0
            st.session_state.top_matches = []

            # Clear displays
            progress_mgr.clear()
            results_container.empty()

            # Process resume
            with st.spinner('Processing resume...'):
                resume_text = extract_resume_text(uploaded_file)

            # Process jobs
            processor = JobProcessor(resume_text, progress_mgr, results_container)
            matched_jobs = processor.process_jobs(
                location=location,
                distance=distance,
                role=keywords,
                days=days_filter,
                included_companies=included_companies,
                excluded_companies=excluded_companies
            )

            # Show final results
            st.session_state.matched_jobs = matched_jobs
            st.session_state.analysis_complete = True
            st.session_state.total_jobs = len(matched_jobs)

            # Clear progress and display final results
            progress_mgr.clear()
            display_results(results_container)

        except Exception as e:
            st.error(f"An error occurred: {str(e)}")
            return

def display_header():
    st.title("Job Scrapping and Matching 💼")
    st.write("Job matching powered by Claude")

def update_progress_display(progress_mgr):
    col1, col2 = st.columns([3, 1])
    with col1:
        progress_mgr.search_placeholder = col1.empty()
    with col2:
        progress_mgr.analysis_placeholder = col2.empty()

def display_live_results(container):
    if st.session_state.top_matches:
        container.markdown("### Live Results")
        for idx, job in enumerate(st.session_state.top_matches, 1):
            with container.expander(
                f"#{idx}: {job['title']} - {job['match_score']}% Match",
                expanded=idx <= 3  # Only expand top 3
            ):
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"**Company:** {job['company']}")
                    st.write(f"**Location:** {job['location']}")
                    st.write(f"**Posted:** {job['posted_date']}")
                with col2:
                    st.metric(
                        label="Match",
                        value=f"{job['match_score']}%"
                    )
                if job['url']:
                    st.button(
                        "Apply Now",
                        key=f"apply_{idx}",
                        use_container_width=True,
                        type="primary"
                    )
                st.write("**Match Analysis:**")
                st.write(job['match_reasoning'])


if __name__ == "__main__":
    main()