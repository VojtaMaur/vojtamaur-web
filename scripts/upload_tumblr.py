#!/usr/bin/env python3
"""
Upload a UTF-8 text file to Tumblr using the Neue Post Format (NPF).

Default behavior:
- blog: vojtamaur.tumblr.com
- state: published immediately
- max 3900 Unicode code points per text block
- no NPF link-formatting objects are created, so URLs stay plain text
- the source file can be supplied as a command-line argument or entered interactively

Install:
    py -m pip install requests requests-oauthlib

Examples:
    py upload_tumblr.py ARCHIVE.txt
    py upload_tumblr.py "F:\\vojtamaur-web\\exports\\ARCHIVE.txt"
    py upload_tumblr.py
    py upload_tumblr.py ARCHIVE.txt --draft
"""

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from urllib.parse import quote

import requests
from requests_oauthlib import OAuth1


DEFAULT_BLOG = "vojtamaur.tumblr.com"
DEFAULT_BLOCK_SIZE = 3900
MAX_BLOCK_SIZE = 4096
MAX_BLOCKS = 1000
APPROX_POST_BYTES_LIMIT = 1_000_000


def get_secret(env_name: str, prompt: str, hidden: bool = True) -> str:
    value = os.environ.get(env_name)
    if value:
        return value.strip()

    value = getpass.getpass(prompt) if hidden else input(prompt)
    value = value.strip()

    if not value:
        raise SystemExit(f"Missing credential: {env_name}")

    return value


def get_file_path(argument: str | None) -> Path:
    if argument:
        return Path(argument)

    entered = input("Path to text file: ").strip()

    # Makes pasted Windows paths such as "F:\\folder\\file.txt" work
    # even if the surrounding quotes are copied too.
    if (
        len(entered) >= 2
        and entered[0] == entered[-1]
        and entered[0] in ('"', "'")
    ):
        entered = entered[1:-1]

    if not entered:
        raise SystemExit("No file path supplied.")

    return Path(entered)


def split_exact(text: str, block_size: int) -> list[str]:
    """
    Split text into <= block_size chunks while preserving the original text.
    Prefer newline boundaries near the end of each chunk.
    """
    chunks = []
    pos = 0

    while pos < len(text):
        end = min(pos + block_size, len(text))

        if end < len(text):
            search_start = max(pos, end - 600)
            cut = text.rfind("\n", search_start, end)
            if cut >= search_start:
                end = cut + 1

        chunk = text[pos:end]

        if not chunk:
            raise RuntimeError("Internal error: empty block produced.")

        chunks.append(chunk)
        pos = end

    return chunks


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Upload a UTF-8 text file to Tumblr as an NPF post."
    )
    parser.add_argument(
        "file",
        nargs="?",
        help=(
            "Text file to upload. May be a filename or full path. "
            "If omitted, the script asks for the path interactively."
        ),
    )
    parser.add_argument(
        "--blog",
        default=DEFAULT_BLOG,
        help=f"Tumblr blog identifier (default: {DEFAULT_BLOG})",
    )
    parser.add_argument(
        "--block-size",
        type=int,
        default=DEFAULT_BLOCK_SIZE,
        help=f"Maximum characters per NPF text block (default: {DEFAULT_BLOCK_SIZE})",
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        help="Create a draft instead of publishing immediately.",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Optional heading inserted before the uploaded text.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build and validate the payload without contacting Tumblr.",
    )
    args = parser.parse_args()

    if not 1 <= args.block_size <= MAX_BLOCK_SIZE:
        raise SystemExit(f"--block-size must be between 1 and {MAX_BLOCK_SIZE}.")

    file_path = get_file_path(args.file)

    if not file_path.is_file():
        raise SystemExit(f"File not found: {file_path}")

    raw = file_path.read_bytes()

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SystemExit(f"{file_path} is not valid UTF-8: {exc}") from exc

    chunks = split_exact(text, args.block_size)

    if "".join(chunks) != text:
        raise SystemExit("Internal verification failed: split text is not exact.")

    post_content = []

    if args.title:
        post_content.append(
            {
                "type": "text",
                "subtype": "heading1",
                "text": args.title,
            }
        )

    # Deliberately no NPF "formatting" field:
    # URLs remain plain text instead of becoming explicit link objects.
    post_content.extend(
        {"type": "text", "text": chunk}
        for chunk in chunks
    )

    if len(post_content) > MAX_BLOCKS:
        raise SystemExit(
            f"Too many NPF blocks: {len(post_content)} > {MAX_BLOCKS}. "
            f"Use a larger --block-size or split the source file."
        )

    state = "draft" if args.draft else "published"

    payload = {
        "content": post_content,
        "state": state,
    }

    payload_bytes = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")

    print(f"File:               {file_path}")
    print(f"UTF-8 bytes:        {len(raw):,}")
    print(f"Unicode characters: {len(text):,}")
    print(f"NPF blocks:         {len(post_content):,}")
    print(f"Largest file block: {max(map(len, chunks)) if chunks else 0:,}")
    print(f"JSON request bytes: {len(payload_bytes):,}")
    print(f"State:              {state}")
    print(f"Blog:               {args.blog}")

    if len(payload_bytes) >= APPROX_POST_BYTES_LIMIT:
        print(
            "WARNING: payload is near/over Tumblr's documented 1 MB content limit.",
            file=sys.stderr,
        )

    if args.dry_run:
        print("\nDry run only. Nothing was sent.")
        return 0

    print("\nTumblr OAuth credentials")
    consumer_key = get_secret(
        "TUMBLR_CONSUMER_KEY",
        "Consumer Key: ",
        hidden=False,
    )
    consumer_secret = get_secret(
        "TUMBLR_CONSUMER_SECRET",
        "Consumer Secret: ",
    )
    oauth_token = get_secret(
        "TUMBLR_OAUTH_TOKEN",
        "OAuth Token: ",
    )
    oauth_token_secret = get_secret(
        "TUMBLR_OAUTH_TOKEN_SECRET",
        "OAuth Token Secret: ",
    )

    auth = OAuth1(
        consumer_key,
        client_secret=consumer_secret,
        resource_owner_key=oauth_token,
        resource_owner_secret=oauth_token_secret,
    )

    blog_identifier = quote(args.blog, safe="")
    url = f"https://api.tumblr.com/v2/blog/{blog_identifier}/posts"

    print("\nSending NPF post to Tumblr...")

    try:
        response = requests.post(
            url,
            json=payload,
            auth=auth,
            timeout=90,
            headers={
                "Accept": "application/json",
                "User-Agent": "vojtamaur.cz-archive/1.0",
            },
        )
    except requests.RequestException as exc:
        raise SystemExit(f"Request failed: {exc}") from exc

    print(f"HTTP {response.status_code}")

    try:
        data = response.json()
        print(json.dumps(data, ensure_ascii=False, indent=2))
    except ValueError:
        data = None
        print(response.text)

    if response.status_code == 201:
        post_id = None

        if isinstance(data, dict):
            post_id = data.get("response", {}).get("id")

        if post_id:
            print(f"\nCreated Tumblr {state} post: ID {post_id}")
        else:
            print(f"\nCreated Tumblr {state} post.")

        return 0

    print(
        "\nTumblr rejected the request. The API response above should include "
        "a useful error/subcode.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
