"""The campus's one allowed write: Mark's own «В архив» / «Вернуть» (Mark 2026-10-25).

The campus stays read-only for agent work. Read-only contract tests strip this one marked
region; ``test_campus_archive`` checks that the region posts only to the owner-guarded archive.
"""
import re

START = "// campus-archive-write:start"
END = "// campus-archive-write:end"


def without_archive_write(text: str) -> str:
    region = re.compile(re.escape(START) + r"[\s\S]*?" + re.escape(END))
    for match in region.finditer(text):
        posts = re.findall(r"fetch\('([^']+)'", match.group(0))
        if posts != ["/api/manager/campus-archive"]:
            raise AssertionError(f"campus archive region writes elsewhere: {posts}")
    return region.sub("", text)
