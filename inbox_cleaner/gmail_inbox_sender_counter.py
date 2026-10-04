from collections import Counter
from itertools import repeat
from pathlib import Path
import time
import multiprocessing
import os.path
import csv
from email.utils import parseaddr
from typing import Any

import click
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
SIZE_BYTES = {"100K": 100_000, "1M": 1_000_000, "5M": 5_000_000, "10M": 10_000_000}


def get_gmail_creds() -> Any:
    creds = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            # TODO - try this out the next time a RefreshError is hit.
            # authorization_url, state = flow.authorization_url(
            #   # Enable offline access so that you can refresh an access token without
            #   # re-prompting the user for permission. Recommended for web server apps.
            #   access_type="offline",
            #   # Enable incremental authorization. Recommended as a best practice.
            #   include_granted_scopes="true")
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open("token.json", "w") as token:
            token.write(creds.to_json())
            print("Successfully signed in, saved credential token.")
    return creds


def fetch_sender_for_threads(gmail_service: Any, thread: Any) -> str:
    t = gmail_service.users().threads().get(userId="me", id=thread["id"]).execute()
    orig_thread_msg = t["messages"][0]
    from_list = list(
        filter(
            lambda h: h["name"].upper() == "FROM", orig_thread_msg["payload"]["headers"]
        )
    )
    assert len(from_list) == 1, (
        f"Could not find 'FROM' header! Thread ID: {thread['id']}, headers: {orig_thread_msg['payload']['headers']}"
    )
    from_sender = from_list[0]["value"]
    return from_sender


def write_sender_counts_to_csv(sender_counts: dict[str, int], filepath: Path) -> None:
    with open(filepath, "w", newline="", encoding="utf-8") as csvfile:
        fieldnames = ["Sender Name", "Sender Email", "Count"]
        writer = csv.writer(csvfile)
        writer.writerow(fieldnames)
        rows = sorted(sender_counts.items(), key=lambda item: item[1], reverse=True)
        writer.writerows(
            [*parseaddr(sender), count] for sender, count in rows
        )


def get_header_value(payload: dict[str, Any], header_name: str) -> str:
    """Find a message header in Gmail's list of name/value header objects.

    Gmail returns headers as a list rather than a mapping, and header-name casing
    can vary. This helper centralizes case-insensitive lookup for the report's
    Date, From, and Subject columns, returning an empty value when a message
    doesn't include the requested header.
    """
    for header in payload.get("headers", []):
        if header.get("name", "").casefold() == header_name.casefold():
            return header.get("value", "")
    return ""


def format_size(size_bytes: int) -> str:
    """Format a byte count using decimal units for the largest-email report."""
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(size_bytes)
    unit_index = 0

    while value >= 1000 and unit_index < len(units) - 1:
        value /= 1000
        unit_index += 1

    rounded_value = round(value, 1)
    if rounded_value >= 1000 and unit_index < len(units) - 1:
        rounded_value /= 1000
        unit_index += 1

    display_value = f"{rounded_value:.1f}".rstrip("0").rstrip(".")
    return f"{display_value} {units[unit_index]}"


def write_largest_emails(gmail_service: Any, size: str, filepath: Path) -> int:
    """Export matching large Gmail messages to CSV and return the number written."""
    query = f"larger:{size}"
    page_token = None
    messages: list[tuple[int, list[str]]] = []

    while True:
        results = (
            gmail_service.users()
            .messages()
            .list(
                userId="me",
                q=query,
                maxResults=500,
                pageToken=page_token,
            )
            .execute(num_retries=5)
        )
        next_page_token = results.get("nextPageToken")

        for message in results.get("messages", []):
            details = (
                gmail_service.users()
                .messages()
                .get(
                    userId="me",
                    id=message["id"],
                    format="metadata",
                    metadataHeaders=["Date", "From", "Subject"],
                )
                .execute(num_retries=5)
            )
            size_bytes = details.get("sizeEstimate", 0)
            if size_bytes < SIZE_BYTES[size]:
                continue

            payload = details.get("payload", {})
            messages.append(
                (
                    size_bytes,
                    [
                        get_header_value(payload, "Date"),
                        get_header_value(payload, "From"),
                        get_header_value(payload, "Subject"),
                        format_size(size_bytes),
                        details.get("threadId", ""),
                    ],
                )
            )

        if not next_page_token:
            break
        page_token = next_page_token

    messages.sort(key=lambda item: item[0], reverse=True)
    with filepath.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Date", "From", "Subject", "Size", "Thread ID"])
        writer.writerows(row for _, row in messages)

    return len(messages)


@click.group()
def cli() -> None:
    pass


@cli.command()
def get_most_frequent_senders() -> None:
    output_folder = Path("output/")
    output_folder.mkdir(exist_ok=True)
    creds = get_gmail_creds()

    sender_counts: dict[str, int] = Counter()
    page_count = 500
    overall_email_count = 10000
    senders = []
    try:
        service = build("gmail", "v1", credentials=creds)
        results = (
            service.users()
            .threads()
            .list(userId="me", q="in:inbox", maxResults=page_count)
            .execute(num_retries=5)
        )
        threads = results.get("threads", [])

        while len(threads) > 0 and sum(sender_counts.values()) < overall_email_count:
            start_time = time.time()
            with multiprocessing.Pool() as pool:
                senders = pool.starmap(
                    fetch_sender_for_threads, zip(repeat(service), threads)
                )
            sender_counts.update(senders)
            end_time = time.time()
            print(f"Time to process {len(threads)} emails: {end_time - start_time}s.")

            if "nextPageToken" not in results:
                # Reached last page
                break

            time.sleep(12)
            results = (
                service.users()
                .threads()
                .list(
                    userId="me",
                    q="in:inbox",
                    maxResults=page_count,
                    pageToken=results["nextPageToken"],
                )
                .execute(num_retries=5)
            )
            threads = results.get("threads", [])
    except HttpError as error:
        raise click.ClickException(f"Gmail API request failed: {error}") from error

    print(f"Processed {sum(sender_counts.values())} emails.")
    write_sender_counts_to_csv(sender_counts, output_folder / "sender_counts.csv")


@cli.command()
@click.option(
    "--size",
    type=click.Choice(["100K", "1M", "5M", "10M"], case_sensitive=True),
    default="1M",
)
@click.option(
    "--output",
    type=click.Path(path_type=Path, dir_okay=False),
    default="largest_emails.csv",
    show_default=True,
)
def get_largest_emails(size: str, output: Path) -> None:
    output_folder = Path("output/")
    output_folder.mkdir(exist_ok=True)
    creds = get_gmail_creds()
    try:
        service = build("gmail", "v1", credentials=creds)
        email_count = write_largest_emails(service, size, output_folder / output)
    except HttpError as error:
        raise click.ClickException(f"Gmail API request failed: {error}") from error
    except OSError as error:
        raise click.ClickException(f"Could not write {output}: {error}") from error

    click.echo(f"Wrote {email_count} emails to {output}.")


if __name__ == "__main__":
    cli()
