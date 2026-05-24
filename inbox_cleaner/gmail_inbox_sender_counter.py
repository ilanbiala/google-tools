from collections import Counter
from itertools import repeat
from pathlib import Path
import time
import multiprocessing
import os.path
import csv
from typing import Any

import click
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


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
    with open(filepath, "w") as csvfile:
        fieldnames = ["Sender", "Count"]
        writer = csv.writer(csvfile)
        writer.writerow(fieldnames)
        rows = sorted(sender_counts.items(), key=lambda item: item[1], reverse=True)
        writer.writerows(rows)


@click.group()
def cli() -> None:
    pass


@cli.command()
def get_most_frequent_senders() -> None:
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
    except Exception as error:
        print(f"An error occurred: {error}")
        breakpoint()

    print(f"Processed {sum(sender_counts.values())} emails.")
    write_sender_counts_to_csv(sender_counts, Path("output.csv"))


@cli.command()
@click.option(
    "--size",
    type=click.Choice(["100K", "1M", "5M", "10M"], case_sensitive=True),
    default="1M",
)
def get_largest_emails(size: str) -> None:
    creds = get_gmail_creds()
    page_count = 500
    try:
        service = build("gmail", "v1", credentials=creds)
        results = (
            service.users()
            .threads()
            .list(userId="me", q=f"larger:{size}", maxResults=page_count)
            .execute()
        )
        threads = results.get("threads", [])
    except Exception as error:
        # TODO(developer) - Handle errors from gmail API.
        print(f"An error occurred: {error}")
        breakpoint()

    raise NotImplementedError()


if __name__ == "__main__":
    cli()
