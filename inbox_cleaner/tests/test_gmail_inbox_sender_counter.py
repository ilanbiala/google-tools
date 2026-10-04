import csv
import tempfile
import unittest
from pathlib import Path
from typing import Any

from gmail_inbox_sender_counter import write_largest_emails


class FakeRequest:
    def __init__(self, result: dict[str, Any]) -> None:
        """Create a fake API request that returns the supplied result."""
        self.result = result

    def execute(self, num_retries: int) -> dict[str, Any]:
        """Return the fake response without making a network request."""
        return self.result


class FakeMessages:
    def __init__(self) -> None:
        """Set up fake message pages and metadata for pagination tests."""
        self.list_calls: list[dict[str, object]] = []
        self.pages = [
            {"messages": [{"id": "first"}, {"id": "second"}], "nextPageToken": "next"},
            {"messages": [{"id": "third"}]},
        ]
        self.details: dict[str, dict[str, Any]] = {
            "first": {
                "sizeEstimate": 1_200_000,
                "threadId": "thread-1",
                "payload": {
                    "headers": [
                        {"name": "From", "value": "sender@example.com"},
                        {"name": "Subject", "value": "Large message"},
                        {"name": "Date", "value": "Sun, 4 Oct 2026 12:00:00 -0400"},
                    ]
                },
            },
            "second": {"sizeEstimate": 900_000, "threadId": "thread-2"},
            "third": {
                "sizeEstimate": 5_100_000,
                "threadId": "thread-3",
                "payload": {"headers": [{"name": "Subject", "value": "Another large one"}]},
            },
        }

    def list(self, **kwargs: object) -> FakeRequest:
        """Record a list request and return the next fake result page."""
        self.list_calls.append(kwargs)
        return FakeRequest(self.pages.pop(0))

    def get(self, **kwargs: object) -> FakeRequest:
        """Return the fake metadata for the requested message ID."""
        return FakeRequest(self.details[str(kwargs["id"])])


class FakeUsers:
    def __init__(self) -> None:
        """Provide the fake messages API used by the Gmail service."""
        self.messages_api = FakeMessages()

    def messages(self) -> FakeMessages:
        """Return the fake messages resource."""
        return self.messages_api


class FakeGmailService:
    def __init__(self) -> None:
        """Provide a fake Gmail users resource for unit tests."""
        self.users_api = FakeUsers()

    def users(self) -> FakeUsers:
        """Return the fake users resource."""
        return self.users_api


class WriteLargestEmailsTests(unittest.TestCase):
    def test_paginates_filters_and_writes_message_details(self) -> None:
        """Verify pagination, size filtering, and the CSV report contents."""
        gmail_service = FakeGmailService()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "largest.csv"

            count = write_largest_emails(gmail_service, "1M", output)

            with output.open(newline="", encoding="utf-8") as csvfile:
                rows = list(csv.reader(csvfile))

        self.assertEqual(count, 2)
        self.assertEqual(
            gmail_service.users_api.messages_api.list_calls[0],
            {"userId": "me", "q": "larger:1M", "maxResults": 500, "pageToken": None},
        )
        self.assertEqual(
            gmail_service.users_api.messages_api.list_calls[1]["pageToken"], "next"
        )
        self.assertEqual(
            rows,
            [
                ["Date", "From", "Subject", "Size (bytes)", "Thread ID"],
                [
                    "Sun, 4 Oct 2026 12:00:00 -0400",
                    "sender@example.com",
                    "Large message",
                    "1200000",
                    "thread-1",
                ],
                ["", "", "Another large one", "5100000", "thread-3"],
            ],
        )


if __name__ == "__main__":
    unittest.main()
