import PyPDF2
from io import BytesIO

def extract_resume_text(uploaded_file) -> str:
    """
    Extracts text content from uploaded PDF resume
    """
    try:
        # Read PDF file
        pdf_reader = PyPDF2.PdfReader(BytesIO(uploaded_file.read()))
        
        # Extract text from all pages
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        
        # Basic cleanup
        text = text.replace('\n\n', '\n').strip()
        
        return text
    
    except Exception as e:
        raise Exception(f"Error processing resume: {str(e)}")
