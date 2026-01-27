# LinkedIn Job Postings Email Notification

Automated system that sends daily email notifications with LinkedIn job postings data and Excel file attachments.

## Features

- ✅ Queries PostgreSQL database for LinkedIn job postings
- ✅ Exports all jobs to formatted Excel file
- ✅ Sends email with Excel attachment via Microsoft Graph API
- ✅ Shows all job postings in HTML table
- ✅ Automated daily execution via GitHub Actions

## Setup Instructions

### 1. Clone the Repository

```bash
git clone <your-repo-url>
cd cron-poster-jobs/cron-email-notification
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file in the `cron-email-notification` directory:

```env
# Azure AD Configuration
AZURE_TENANT_ID=your-tenant-id
AZURE_CLIENT_ID=your-client-id
AZURE_CLIENT_SECRET=your-client-secret

# Email Configuration
SENDER_EMAIL=support@applywizz.com
CC_EMAIL_RECIPIENTS=email1@example.com,email2@example.com

# Database Configuration
DATABASE_URL=postgresql://user:password@host:port/database
```

### 4. Set Up GitHub Secrets

For the automated cron job to work, add these secrets to your GitHub repository:

1. Go to your repository on GitHub
2. Navigate to **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret** and add each of the following:

| Secret Name | Description |
|-------------|-------------|
| `AZURE_TENANT_ID` | Your Azure AD Tenant ID |
| `AZURE_CLIENT_ID` | Your Azure AD Application (Client) ID |
| `AZURE_CLIENT_SECRET` | Your Azure AD Client Secret |
| `SENDER_EMAIL` | Email address to send from (e.g., support@applywizz.com) |
| `CC_EMAIL_RECIPIENTS` | Comma-separated list of CC recipients |
| `DATABASE_URL` | PostgreSQL database connection string |

### 5. GitHub Actions Cron Job

The workflow is configured in `.github/workflows/daily-email.yml`:

- **Schedule**: Runs every day at 9:00 AM UTC (2:30 PM IST)
- **Manual Trigger**: Can be triggered manually from the Actions tab
- **Automatic**: Yes, emails with Excel attachments will be sent automatically

#### How It Works

1. GitHub Actions triggers the workflow daily at the scheduled time
2. Sets up Python environment and installs dependencies
3. Runs `api_send_email_notification.py` with environment variables from secrets
4. Script queries database, generates Excel file, and sends email
5. Email includes:
   - All job postings in HTML table
   - Excel file attachment with all data
   - Professional formatting

#### Manual Trigger

To manually trigger the workflow:

1. Go to your repository on GitHub
2. Click **Actions** tab
3. Select **Daily LinkedIn Job Postings Email** workflow
4. Click **Run workflow** button
5. Select branch and click **Run workflow**

## Local Testing

To test locally:

```bash
cd cron-email-notification
python api_send_email_notification.py
```

Or start the FastAPI server:

```bash
uvicorn api_send_email_notification:app --reload --port 8000
```

Then trigger the endpoint:

```bash
curl -X POST http://localhost:8000/get-linkedin-jobs
```

## Email Output

The automated email includes:

- **Subject**: LinkedIn Job Postings Report: X LinkedIn Job Posting(s) - YYYY-MM-DD
- **To**: Configured recipient
- **CC**: Configured CC recipients
- **Attachment**: Excel file with all job postings
- **Body**: 
  - Summary of job count
  - Attachment notice
  - Full HTML table with all jobs
  - Quick statistics

## File Structure

```
cron-email-notification/
├── .github/
│   └── workflows/
│       └── daily-email.yml          # GitHub Actions workflow
├── exports/                          # Generated Excel files (gitignored)
├── api_send_email_notification.py   # Main script
├── requirements.txt                  # Python dependencies
├── .gitignore                        # Git ignore rules
└── README.md                         # This file
```

## Troubleshooting

### Emails Not Sending

1. Check GitHub Actions logs for errors
2. Verify all secrets are correctly set
3. Ensure Azure AD app has proper permissions
4. Check database connectivity

### Excel File Not Attached

1. Verify `pandas` and `openpyxl` are installed
2. Check file size (must be under 4MB for inline attachments)
3. Review server logs for attachment errors

### Cron Job Not Running

1. Check workflow file syntax
2. Verify workflow is enabled in GitHub Actions
3. Check if repository has Actions enabled
4. Review workflow run history for errors

## Support

For issues or questions, please open an issue in the repository.
