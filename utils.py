import pandas as pd
import io

def export_to_csv(matches_df: pd.DataFrame) -> str:
    """
    Exports matched jobs to CSV format
    """
    # Select relevant columns for export
    export_columns = [
        'title', 'company', 'location', 'posted_date',
        'match_score', 'match_reasoning'
    ]
    
    # Create CSV in memory
    output = io.StringIO()
    matches_df[export_columns].to_csv(output, index=False)
    return output.getvalue()
