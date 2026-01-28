#karmafy/karmafy/api_send_email_notification.py

from fastapi import FastAPI, HTTPException
from typing import Optional
import requests
import os
from datetime import datetime
import psycopg2
from psycopg2.extras import RealDictCursor
import pandas as pd
import base64

# -----------------------
# Config - Load from environment variables
# -----------------------
# Load .env file from parent directory
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(env_path)

# Azure AD Configuration - REQUIRED
TENANT_ID = os.getenv("AZURE_TENANT_ID")
CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", "support@applywizz.com")

# Validate required Azure credentials
if not all([TENANT_ID, CLIENT_ID, CLIENT_SECRET]):
    raise ValueError(
        "Missing required Azure AD credentials. Please set the following environment variables:\n"
        "  - AZURE_TENANT_ID\n"
        "  - AZURE_CLIENT_ID\n"
        "  - AZURE_CLIENT_SECRET"
    )

# Database configuration - REQUIRED
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError(
        "Missing required DATABASE_URL environment variable. "
        "Please set it in your .env file."
    )

APP_NAME = "LinkedIn Job Postings Report"

# Email recipient for job postings report
TEST_EMAIL_RECIPIENT = "bhanutejathouti@gmail.com"
# CC Recipients - comma-separated list of email addresses
# Can be set via environment variable: CC_EMAIL_RECIPIENTS="email1@example.com,email2@example.com"
CC_RECIPIENTS_STR = os.getenv("CC_EMAIL_RECIPIENTS", "")
CC_EMAIL_RECIPIENTS = [email.strip() for email in CC_RECIPIENTS_STR.split(",") if email.strip()]

# Excel exports directory
EXPORTS_DIR = Path(__file__).parent / "exports"
EXPORTS_DIR.mkdir(exist_ok=True)

# FastAPI app
app = FastAPI()


# -----------------------
# Database Connection
# -----------------------
def get_db_connection():
    """Get PostgreSQL database connection"""
    try:
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    except Exception as e:
        print(f"❌ Database connection error: {e}")
        raise HTTPException(status_code=500, detail="Database connection failed")


# -----------------------
# Query LinkedIn Job Postings
# -----------------------
def get_linkedin_job_postings(target_date: Optional[str] = None):
    """
    Query the karmafy_job table to find all job postings from high-volume posters.
    Returns jobs from poster profiles that have posted more than 2 jobs today.
    
    Args:
        target_date: Date in 'YYYY-MM-DD' format. Defaults to today's date if not provided.
    
    Returns list of dicts with job posting information.
    """
    conn = get_db_connection()
    try:
        # If no date provided, use today's date
        if target_date is None:
            target_date = datetime.now().strftime('%Y-%m-%d')
        
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            query = """
                SELECT
                    company,
                    title,
                    posted_by_profile,
                    poster_full_name,
                    url,
                    company_url,
                    source
                FROM public.karmafy_job
                WHERE "ingestedAt" >= CURRENT_DATE
                    AND "ingestedAt" < CURRENT_DATE + INTERVAL '1 day'
                    AND posted_by_profile IS NOT NULL
                    AND posted_by_profile <> ''
                    AND posted_by_profile IN (
                        SELECT posted_by_profile
                        FROM public.karmafy_job
                        WHERE "ingestedAt" >= CURRENT_DATE
                            AND "ingestedAt" < CURRENT_DATE + INTERVAL '1 day'
                            AND posted_by_profile IS NOT NULL
                            AND posted_by_profile <> ''
                        GROUP BY posted_by_profile
                        HAVING COUNT(DISTINCT title) > 2
                    )
                ORDER BY posted_by_profile, title
            """
            cursor.execute(query)
            results = cursor.fetchall()
            
            # Convert to list of dicts
            return [dict(row) for row in results]
    
    except psycopg2.Error as e:
        print(f"❌ Database query error: {e}")
        raise HTTPException(status_code=500, detail="Database query failed")
    finally:
        conn.close()


# Azure AD token
def get_access_token() -> str:
    token_url = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }

    res = requests.post(token_url, data=data)
    if not res.ok:
        try:
            error_text = res.text
        except Exception:
            error_text = "<no body>"
        print("❌ Error getting access token:", res.status_code, error_text)
        raise HTTPException(status_code=500, detail="Failed to get access token from Azure AD")

    json_data = res.json()
    access_token = json_data.get("access_token")
    if not access_token:
        print("❌ No access_token in token response:", json_data)
        raise HTTPException(status_code=500, detail="No access token received from Azure AD")

    return access_token


# -----------------------
# Send mail via Graph
# -----------------------
def send_mail_via_graph(to: str, subject: str, html: str, cc: Optional[list] = None, attachment_path: Optional[str] = None) -> None:
    """
    Send email via Microsoft Graph API.
    
    Args:
        to: Primary recipient email address
        subject: Email subject
        html: HTML email content
        cc: Optional list of CC email addresses
        attachment_path: Optional path to file to attach
    """
    access_token = get_access_token()

    url = f"https://graph.microsoft.com/v1.0/users/{SENDER_EMAIL}/sendMail"

    payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": html,
            },
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": to
                    }
                }
            ],
        },
        "saveToSentItems": True,
    }
    
    # Add CC recipients if provided
    if cc and len(cc) > 0:
        payload["message"]["ccRecipients"] = [
            {"emailAddress": {"address": email}} for email in cc
        ]
    
    # Add attachment if provided
    if attachment_path and os.path.exists(attachment_path):
        try:
            with open(attachment_path, 'rb') as f:
                file_content = f.read()
            
            # Encode to base64 - ensure no newlines or whitespace
            file_base64 = base64.b64encode(file_content).decode('ascii')
            filename = os.path.basename(attachment_path)
            file_size_kb = len(file_content) / 1024
            
            # Check file size (Microsoft Graph has 4MB limit for inline attachments)
            if len(file_content) > 4 * 1024 * 1024:
                print(f"⚠️ Warning: File size ({file_size_kb:.1f} KB) exceeds 4MB limit for inline attachments")
            
            payload["message"]["attachments"] = [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": filename,
                    "contentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "contentBytes": file_base64
                }
            ]
            print(f"📎 Attachment added: {filename} ({file_size_kb:.1f} KB, base64: {len(file_base64):,} chars)")
        except Exception as e:
            print(f"❌ Error adding attachment: {e}")
            raise
    else:
        if attachment_path:
            print(f"⚠️ Attachment file not found: {attachment_path}")
        else:
            print("ℹ️ No attachment path provided")

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    res = requests.post(url, json=payload, headers=headers)
    if not res.ok:
        try:
            error_text = res.text
        except Exception:
            error_text = "<no body>"
        print("❌ Error sending email via Graph:", res.status_code, error_text)
        raise HTTPException(status_code=500, detail="Failed to send email via Microsoft Graph")


# -----------------------
# Export Jobs to Excel
# -----------------------
def export_jobs_to_excel(jobs_data: list) -> str:
    """
    Export job postings data to an Excel file.
    
    Args:
        jobs_data: List of job posting dictionaries
    
    Returns:
        Absolute file path to the generated Excel file
    """
    # Generate filename with timestamp
    timestamp = datetime.now().strftime('%Y-%m-%d_%H%M%S')
    filename = f"linkedin_jobs_{timestamp}.xlsx"
    filepath = EXPORTS_DIR / filename
    
    # Prepare data for DataFrame
    excel_data = []
    for idx, job in enumerate(jobs_data, 1):
        excel_data.append({
            '#': idx,
            'Company': job.get('company', 'N/A') or 'N/A',
            'Job Title': job.get('title', 'N/A') or 'N/A',
            'Posted By': job.get('poster_full_name', 'N/A') or 'N/A',
            'Profile URL': job.get('posted_by_profile', '') or '',
            'Job URL': job.get('url', '') or '',
            'Company URL': job.get('company_url', '') or '',
            'Source': job.get('source', 'N/A') or 'N/A',
        })
    
    # Create DataFrame
    df = pd.DataFrame(excel_data)
    
    # Export to Excel with formatting
    with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='LinkedIn Jobs')
        
        # Get the worksheet
        worksheet = writer.sheets['LinkedIn Jobs']
        
        # Auto-adjust column widths
        for column in worksheet.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)  # Cap at 50 characters
            worksheet.column_dimensions[column_letter].width = adjusted_width
        
        # Make header row bold
        for cell in worksheet[1]:
            cell.font = cell.font.copy(bold=True)
    
    print(f"✅ Excel file created: {filepath}")
    return str(filepath.absolute())



def build_job_postings_email_template(
    app_name: str,
    jobs_data: list,
    excel_filepath: str,
    support_url: str = "https://dashboard.apply-wizz.com/",
) -> str:
    """Build the HTML email template with LinkedIn job postings data and Excel download link"""
    
    # Build table rows for all job postings
    jobs_rows = ""
    for idx, job in enumerate(jobs_data, 1):
        company = job.get('company', 'N/A') or 'N/A'
        title = job.get('title', 'N/A') or 'N/A'
        url = job.get('url', '#') or '#'
        company_url = job.get('company_url', '#') or '#'
        poster_full_name = job.get('poster_full_name', 'N/A') or 'N/A'
        posted_by_profile = job.get('posted_by_profile', '#') or '#'
        source = job.get('source', 'N/A') or 'N/A'
        
        jobs_rows += f"""
        <tr style="border-bottom: 1px solid #e5e7eb;">
            <td style="padding: 10px 8px; text-align: center; color: #6b7280; font-weight: 600; font-size: 13px;">{idx}</td>
            <td style="padding: 10px 8px; color: #111827; font-weight: 600; font-size: 13px;">
                <a href="{company_url}" target="_blank" style="color: #2563eb; text-decoration: none;">{company}</a>
            </td>
            <td style="padding: 10px 8px; color: #111827; font-size: 13px;">
                <a href="{url}" target="_blank" style="color: #059669; text-decoration: none; font-weight: 500;">{title}</a>
            </td>
            <td style="padding: 10px 8px; color: #5b21b6; font-weight: 600; font-size: 13px;">
                <a href="{posted_by_profile}" target="_blank" style="color: #5b21b6; text-decoration: none;">{poster_full_name}</a>
            </td>
            <td style="padding: 10px 8px; text-align: center; color: #6b7280; font-size: 12px; text-transform: uppercase;">{source}</td>
        </tr>
        """
    
    # Debug: Log how many rows were generated
    print(f"📊 Generated {len(jobs_data)} rows for email HTML table")
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charSet="UTF-8" />
  <title>{app_name} – Daily Report</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body {{
      margin: 0;
      padding: 0;
      background-color: #f3f4f6;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: #111827;
    }}
    .container {{
      max-width: 1100px;
      margin: 32px auto;
      background: #ffffff;
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 18px 45px rgba(15, 23, 42, 0.12);
    }}
    .header {{
      background: linear-gradient(135deg, #0a66c2, #0077b5);
      padding: 24px 32px;
      color: white;
      text-align: left;
    }}
    .title {{
      margin-top: 10px;
      font-size: 24px;
      font-weight: 700;
      color: white;
    }}
    .sub {{
      margin-top: 6px;
      font-size: 14px;
      opacity: 0.9;
      color: white;
    }}
    .body {{
      padding: 24px 32px 32px;
      font-size: 14px;
      line-height: 1.6;
    }}
    .info-box {{
      background-color: #eff6ff;
      border-left: 4px solid #0a66c2;
      padding: 16px;
      margin: 20px 0;
      border-radius: 8px;
    }}
    .table-wrapper {{
      overflow-x: auto;
      margin: 20px 0;
    }}
    table {{
      width: 100%;
      min-width: 800px;
      border-collapse: collapse;
      background: white;
      border: 1px solid #e5e7eb;
      border-radius: 8px;
      overflow: hidden;
    }}
    th {{
      background: #f9fafb;
      padding: 12px 8px;
      text-align: left;
      font-weight: 700;
      font-size: 11px;
      text-transform: uppercase;
      letter-spacing: 0.03em;
      color: #6b7280;
      border-bottom: 2px solid #e5e7eb;
      white-space: nowrap;
    }}
    td {{
      padding: 10px 8px;
      font-size: 13px;
      border-bottom: 1px solid #f3f4f6;
    }}
    th:nth-child(1), th:nth-child(5) {{
      text-align: center;
    }}
    td:nth-child(1), td:nth-child(5) {{
      text-align: center;
    }}
    .footer {{
      padding: 16px 32px 24px;
      font-size: 11px;
      color: #9ca3af;
      text-align: center;
    }}
    .cta-button {{
      display: inline-block;
      margin-top: 18px;
      padding: 12px 24px;
      background: linear-gradient(135deg, #0a66c2, #0077b5);
      color: white !important;
      text-decoration: none;
      border-radius: 999px;
      font-weight: 600;
      font-size: 14px;
    }}
    a {{
      color: #0a66c2;
      text-decoration: none;
    }}
    a:hover {{
      text-decoration: underline;
    }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <div class="title">📊 LinkedIn Job Postings Report</div>
      <div class="sub">
        {len(jobs_data)} job posting(s) from high-volume posters (3+ jobs today)
      </div>
    </div>
    <div class="body">
      <p>Hi Team,</p>
      <p>
        This is your daily automated report of <strong>{len(jobs_data)} job posting(s)</strong> from high-volume posters who have posted more than 2 jobs today.
      </p>

      <div class="info-box">
        <strong>ℹ️ Report Details:</strong> This report includes all jobs from poster profiles that have posted <strong>more than 2 jobs today</strong>. These high-volume posters may be recruiters or hiring managers with multiple open positions.
      </div>

      <div style="background: linear-gradient(135deg, #0a66c2, #0077b5); padding: 24px; border-radius: 12px; margin: 24px 0; text-align: center;">
        <h3 style="color: white; margin: 0 0 12px 0;">📎 Excel Report Attached</h3>
        <p style="color: white; opacity: 0.95; margin: 0 0 16px 0; font-size: 14px;">
          All {len(jobs_data)} job postings are available in the attached Excel file
        </p>
        <div style="display: inline-block; padding: 14px 32px; background: white; color: #0a66c2; border-radius: 999px; font-weight: 700; font-size: 15px; box-shadow: 0 4px 12px rgba(0,0,0,0.15);">
          📊 {excel_filepath.split(chr(92))[-1] if excel_filepath else 'Excel Report'}
        </div>
        <p style="color: white; opacity: 0.85; margin: 12px 0 0 0; font-size: 12px;">
          Check your email attachments to download the file
        </p>
      </div>

      <h3 style="color: #111827; margin-top: 24px;">All Job Postings ({len(jobs_data)} Jobs)</h3>
      
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Company</th>
              <th>Job Title</th>
              <th>Posted By</th>
              <th>Source</th>
            </tr>
          </thead>
          <tbody>
            {jobs_rows}
          </tbody>
        </table>
      </div>

      <p style="margin-top: 16px; padding: 12px; background: #f0fdf4; border-left: 4px solid #10b981; color: #065f46; font-size: 13px; border-radius: 4px;">
        ✅ <strong>Table Complete:</strong> Showing all {len(jobs_data)} job postings above (rows 1-{len(jobs_data)})
      </p>

      <p style="margin-top: 24px; color: #6b7280; font-size: 13px;">
        <strong>Quick Stats:</strong>
      </p>
      <ul style="color: #6b7280; font-size: 13px;">
        <li>Total job postings: {len(jobs_data)}</li>
        <li>Filter criteria: Poster profiles with 3+ jobs posted today</li>
        <li>All postings include poster profile information</li>
        <li>Posted date: {datetime.now().strftime('%Y-%m-%d')}</li>
      </ul>

      <a href="{support_url}" class="cta-button" target="_blank" rel="noopener noreferrer">
        View Dashboard
      </a>

      <p style="margin-top: 24px; color: #9ca3af; font-size: 12px;">
        This is an automated notification from {app_name}. Generated on {datetime.now().strftime('%Y-%m-%d %H:%M IST')}.
      </p>
    </div>
    <div class="footer">
      © {datetime.now().year} {app_name}. All rights reserved.
    </div>
  </div>
</body>
</html>
"""
    
    return html

# -----------------------
# NEW ENDPOINT: Get LinkedIn Job Postings
# -----------------------
@app.post("/get-linkedin-jobs")
def get_linkedin_jobs():
    """
    Get all job postings from high-volume posters (3+ jobs posted today).
    Send ONE email with a summary of all job postings.
    """
    # Query database for LinkedIn job postings
    job_postings = get_linkedin_job_postings()
    
    if not job_postings:
        return {
            "success": True,
            "message": "No high-volume posters found today (no profiles with 3+ job postings)!",
            "jobs_count": 0,
            "email_sent": False
        }
    
    # Export jobs to Excel
    excel_filepath = export_jobs_to_excel(job_postings)
    
    # Build email with all job postings information
    subject = f"{APP_NAME}: {len(job_postings)} Job(s) from High-Volume Posters - {datetime.now().strftime('%Y-%m-%d')}"
    
    html = build_job_postings_email_template(
        app_name=APP_NAME,
        jobs_data=job_postings,
        excel_filepath=excel_filepath,
    )
    
    # Send email with all job postings information (with CC and Excel attachment)
    send_mail_via_graph(
        to=TEST_EMAIL_RECIPIENT,
        subject=subject,
        html=html,
        cc=CC_EMAIL_RECIPIENTS,
        attachment_path=excel_filepath,
    )
    
    print(f"✅ LinkedIn job postings email sent to {TEST_EMAIL_RECIPIENT}")
    print(f"   Total job postings: {len(job_postings)}")
    for job in job_postings[:5]:  # Print first 5
        print(f"   - {job['company']}: {job['title']}")
    if len(job_postings) > 5:
        print(f"   ... and {len(job_postings) - 5} more")
    
    return {
        "success": True,
        "message": f"Found {len(job_postings)} job posting(s) from high-volume posters - email sent with Excel report",
        "jobs_count": len(job_postings),
        "jobs": job_postings,
        "email_sent": True,
        "email_sent_to": TEST_EMAIL_RECIPIENT,
        "excel_file": excel_filepath
    }


# Health check endpoint
@app.get("/")
def health_check():
    return {"status": "ok", "service": "LinkedIn Job Postings Notification API"}


# -----------------------
# Main execution when run as script (for cron jobs)
# -----------------------
if __name__ == "__main__":
    print("🚀 Starting LinkedIn job postings check...")
    try:
        result = get_linkedin_jobs()
        print(f"✅ Execution completed successfully!")
        print(f"Result: {result}")
    except Exception as e:
        print(f"❌ Error occurred: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
