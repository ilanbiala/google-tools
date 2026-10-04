# inbox-cleaner
Inbox Cleaner helps you clean out your inbox to free up space in ways Google doesn't currently offer. See the usage section for details.

## Installation
```shell
uv sync
```

## Gmail API setup
1. Create a Google Cloud project and enable the Gmail API.
2. Configure an OAuth consent screen and create an OAuth client ID for a Desktop app.
3. Download the client JSON as `credentials.json` in the directory where you will run the script.
4. Run a command below. The first run opens a browser for Google authorization and saves a local `token.json` for later runs.

The tool requests read-only Gmail access. Keep `credentials.json` and `token.json` private; do not commit or share them.

## Usage
Run commands from the `inbox_cleaner` directory:

```shell
uv run python gmail_inbox_sender_counter.py get-most-frequent-senders
uv run python gmail_inbox_sender_counter.py get-largest-emails --size 5M
```

The sender report is written to `output.csv`. The largest-email report defaults to `largest_emails.csv`; use `--output PATH` to choose a different destination.

### Most Frequent Senders
The `get-most-frequent-senders` subcommand scans your inbox and finds the most frequent senders so you can delete those emails and unsubscribe to them as needed. Its CSV output contains sender name, sender email, and sender count columns.

### Largest Emails
The `get-largest-emails` subcommand scans messages larger than the selected size (`100K`, `1M`, `5M`, or `10M`) and exports their date, sender, subject, human-readable size (using decimal units such as `128 KB` or `1.4 MB`), and Gmail thread ID, sorted from largest to smallest. Google's free up space tool offers something similar to this.
