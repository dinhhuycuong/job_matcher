import anthropic
import os
import sys
from typing import List, Dict, Callable, Optional
import logging
from dotenv import load_dotenv
import time
import random

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def wait_with_backoff(retry_count: int) -> None:
    """Implements exponential backoff with jitter"""
    base_delay = 20  # Increased base delay to 20 seconds
    max_delay = 120  # Maximum delay of 2 minutes
    
    delay = min(base_delay * (2 ** retry_count), max_delay)
    jitter = random.uniform(0.5, 1.5)  # Add 50% jitter
    final_delay = delay * jitter
    
    logger.info(f"Rate limit hit, waiting for {final_delay:.1f} seconds before retry...")
    time.sleep(final_delay)

def analyze_job_match(resume_text: str, job: Dict, client, retry_count: int = 0) -> Dict:
    """Helper function to analyze a single job match with rate limiting"""
    max_retries = 5  # Increased max retries
    
    try:
        logger.info(f"Starting analysis for job: {job['title']} at {job['company']}")
        
        # Initial delay before any API call
        time.sleep(random.uniform(5, 10))  # Increased initial delay
        
        # Log truncated description for debugging
        desc_preview = job['description'][:200] + "..." if len(job['description']) > 200 else job['description']
        logger.info(f"Job description preview: {desc_preview}")
        
        # Construct more concise prompt
        prompt = f"""Rate this job match between 0-100 based on how well the candidate's resume matches the job requirements.

        JOB:
        Title: {job['title']}
        Company: {job['company']}
        Description: {job['description']}

        RESUME:
        {resume_text}

        Respond ONLY in this exact format:
        [Score]|[2-3 key reasons for the score]

        Example: "85|Strong product management background, healthcare industry experience, leadership skills"
        """

        logger.info("Sending request to Claude API...")
        
        try:
            response = client.messages.create(
                model="claude-3-opus-20240229",
                max_tokens=1000,
                messages=[{
                    "role": "user", 
                    "content": prompt
                }],
                temperature=0.5
            )
            
            time.sleep(5)  # Wait after successful API call
            
        except anthropic.RateLimitError:
            if retry_count < max_retries:
                retry_count += 1
                wait_with_backoff(retry_count)
                return analyze_job_match(resume_text, job, client, retry_count)
            else:
                raise Exception(f"Rate limit exceeded after {max_retries} retries")

        logger.info("Received response from Claude")
        response_text = response.content[0].text.strip()
        logger.info(f"Raw response: {response_text}")

        try:
            if '|' not in response_text:
                raise ValueError("Response does not contain expected '|' separator")
                
            score_part, reasoning = response_text.split('|', 1)
            digits = ''.join(filter(str.isdigit, score_part))
            
            if not digits:
                raise ValueError("No digits found in score part")
                
            match_score = int(digits)
            if match_score < 0 or match_score > 100:
                raise ValueError(f"Score {match_score} is outside valid range 0-100")
                
            match_reasoning = reasoning.strip()
            if not match_reasoning:
                raise ValueError("Empty reasoning")
                
            logger.info(f"Successfully parsed - Score: {match_score}, Reasoning: {match_reasoning}")
            
            # Add analysis to job dict
            job_with_match = job.copy()
            job_with_match.update({
                "match_score": match_score,
                "match_reasoning": match_reasoning
            })

            return job_with_match

        except Exception as parse_error:
            logger.error(f"Error parsing response: {parse_error}")
            logger.error(f"Problematic response: {response_text}")
            return {**job, "match_score": 0, "match_reasoning": "Error parsing analysis results"}

    except Exception as e:
        logger.error(f"Error analyzing job: {str(e)}", exc_info=True)
        return {**job, "match_score": 0, "match_reasoning": f"Error during analysis: {str(e)}"}

def analyze_matches(resume_text: str, jobs: List[Dict], progress_callback: Optional[Callable[[Dict], None]] = None) -> List[Dict]:
    """Uses Claude to analyze and score job matches"""
    try:
        anthropic_key = os.getenv('ANTHROPIC_API_KEY')
        if not anthropic_key:
            raise ValueError('ANTHROPIC_API_KEY environment variable must be set')

        client = anthropic.Anthropic(api_key=anthropic_key)
        logger.info(f"Starting analysis of {len(jobs)} jobs")
        matched_jobs = []

        for index, job in enumerate(jobs, 1):
            logger.info(f"Processing job {index}/{len(jobs)}")
            job_with_match = analyze_job_match(resume_text, job, client)
            matched_jobs.append(job_with_match)
            
            if progress_callback:
                progress_callback(job_with_match)

            # Add delay between jobs
            time.sleep(random.uniform(10, 15))

        # Sort by match score
        matched_jobs.sort(key=lambda x: x.get('match_score', 0), reverse=True)
        return matched_jobs

    except Exception as e:
        logger.error("Error in analyze_matches:", exc_info=True)
        # Return original jobs with zero scores on error
        return [{**job, "match_score": 0, "match_reasoning": "Analysis failed"} for job in jobs]