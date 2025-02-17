import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import List, Dict, Callable, Optional, Union, Generator
import re
import time
import random
from urllib.parse import urlencode
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def parse_company_list(companies_text: str) -> set:
    """Parse company names from text input"""
    if not companies_text:
        return set()
    return {company.strip().lower() for company in companies_text.split('\n') if company.strip()}

def should_include_company(company: str, included_companies: set, excluded_companies: set) -> bool:
    """
    Determine if a job from a company should be included based on filters
    """
    company = company.lower()
    
    # Check excluded companies first
    for excluded in excluded_companies:
        if excluded in company:
            return False
    
    # If no included companies specified, include all (except excluded)
    if not included_companies:
        return True
    
    # Check if company matches any included company
    for included in included_companies:
        if included in company:
            return True
            
    return False

def scrape_linkedin_jobs(
    location: str, 
    distance: int, 
    role: str, 
    days: int = None, 
    progress_callback: Optional[Callable[[int], None]] = None,
    stream_jobs: bool = True,
    included_companies: str = "",
    excluded_companies: str = ""
) -> Union[List[Dict], Generator[Dict, None, None]]:
    """
    Scrapes LinkedIn jobs based on given parameters
    """
    # Parse company filters
    included = parse_company_list(included_companies)
    excluded = parse_company_list(excluded_companies)
    
    base_url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    jobs = []
    total_jobs_found = 0
    filtered_count = 0
    start = 0
    max_jobs = 3000

    try:
        while total_jobs_found < max_jobs:
            # Construct request parameters
            params = {
                'keywords': role,
                'location': location,
                'distance': distance,
                'sortBy': 'DD',
                'start': start
            }

            if days is not None:
                params['f_TPR'] = f'r{days * 86400}'

            url = f"{base_url}?{urlencode(params)}"
            logger.info(f"Fetching jobs batch starting at {start}")

            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': 'https://www.linkedin.com/',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }

            try:
                response = requests.get(url, headers=headers, timeout=10)
                response.raise_for_status()
                
                soup = BeautifulSoup(response.text, 'html.parser')
                job_cards = soup.find_all('div', {'class': ['base-card', 'job-search-card']})

                if not job_cards:
                    logger.info("No more job cards found")
                    break

                for card in job_cards:
                    try:
                        title_elem = card.find(['h3', 'h4'], {'class': ['base-search-card__title', 'job-search-card__title']})
                        company_elem = card.find(['h4', 'h5'], {'class': ['base-search-card__subtitle', 'job-search-card__subtitle']})
                        location_elem = card.find('span', {'class': ['job-search-card__location', 'job-result-card__location']})
                        time_elem = card.find('time', {'class': ['job-search-card__listdate', 'job-result-card__listdate']})

                        if title_elem and company_elem:
                            company = company_elem.text.strip()
                            
                            # Apply company filters
                            if not should_include_company(company, included, excluded):
                                continue
                                
                            title = title_elem.text.strip()
                            job_location = location_elem.text.strip() if location_elem else location

                            link_elem = card.find('a', {'class': ['base-card__full-link', 'job-card-container__link']})
                            job_url = link_elem.get('href') if link_elem else None

                            description = get_job_description(job_url) if job_url else f"Position: {title}\nCompany: {company}\nLocation: {job_location}"

                            posted_date = datetime.now() - timedelta(hours=random.randint(1, 24))
                            if time_elem:
                                try:
                                    date_str = time_elem.get('datetime')
                                    posted_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                                except:
                                    pass

                            job_data = {
                                "title": title,
                                "company": company,
                                "location": job_location,
                                "description": description,
                                "posted_date": posted_date.strftime("%Y-%m-%d %H:%M:%S"),
                                "url": job_url
                            }

                            filtered_count += 1
                            
                            if progress_callback:
                                progress_callback(filtered_count)

                            if stream_jobs:
                                yield job_data
                            else:
                                jobs.append(job_data)

                            if filtered_count >= max_jobs:
                                logger.info("Reached maximum jobs limit")
                                break

                        total_jobs_found += 1

                    except Exception as e:
                        logger.error(f"Error processing job card: {str(e)}")
                        continue

                if filtered_count >= max_jobs:
                    break

                start += len(job_cards)
                time.sleep(random.uniform(2, 4))

            except requests.RequestException as e:
                logger.error(f"Request error: {str(e)}")
                time.sleep(random.uniform(5, 10))
                continue

    except Exception as e:
        logger.error(f"Error scraping jobs: {str(e)}")
        if stream_jobs:
            yield from get_sample_jobs(role, location)
        else:
            return get_sample_jobs(role, location) if not jobs else jobs

    if stream_jobs:
        if not filtered_count:
            yield from get_sample_jobs(role, location)
    else:
        return jobs if jobs else get_sample_jobs(role, location)

def get_job_description(url: str) -> str:
    """Get detailed job description from job page"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        description_selectors = [
            'div.description__text',
            'div.show-more-less-html__markup',
            'div.job-description',
            'div.description'
        ]
        
        for selector in description_selectors:
            description_elem = soup.select_one(selector)
            if description_elem:
                return description_elem.text.strip()
                
        description_keywords = ['job description', 'position description', 'role description']
        for keyword in description_keywords:
            desc_elem = soup.find(lambda tag: tag.name in ['div', 'section'] and 
                                keyword.lower() in tag.text.lower())
            if desc_elem:
                return desc_elem.text.strip()
                
        time.sleep(random.uniform(1, 2))
        
    except Exception as e:
        logger.error(f"Error fetching job description: {str(e)}")
    
    return "Detailed description not available"

def get_sample_jobs(role: str, location: str) -> List[Dict]:
    """Return sample jobs as fallback"""
    logger.info("Using sample jobs data as fallback")
    
    sample_jobs = []
    job_titles = [
        f"Senior {role}",
        f"Lead {role}",
        f"Principal {role}",
        f"Staff {role}",
        f"{role} Manager"
    ]
    
    companies = [
        "Tech Corp Inc",
        "Digital Solutions Ltd",
        "Innovation Systems",
        "Future Technologies",
        "Global Tech Partners"
    ]
    
    descriptions = [
        f"We are seeking an experienced {role} to join our team. The ideal candidate will have 5+ years of experience in product development, strong leadership skills, and a track record of successful product launches.",
        f"Join our growing team as a {role}. You will be responsible for driving innovation, leading cross-functional teams, and delivering high-impact solutions.",
        f"Exciting opportunity for a seasoned {role} to make a significant impact. You will lead strategic initiatives, mentor team members, and shape the future of our products.",
        f"We're looking for a talented {role} to help scale our operations. The ideal candidate brings deep expertise, creative problem-solving skills, and a passion for excellence.",
        f"Outstanding opportunity for a {role} to join our dynamic team. You will drive key projects, collaborate with stakeholders, and contribute to our company's growth."
    ]
    
    for i in range(5):
        hours_ago = random.randint(1, 24)
        sample_jobs.append({
            "title": job_titles[i],
            "company": companies[i],
            "location": location,
            "description": descriptions[i],
            "posted_date": (datetime.now() - timedelta(hours=hours_ago)).strftime("%Y-%m-%d %H:%M:%S"),
            "url": None
        })
    
    return sample_jobs