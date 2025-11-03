"""
Shared audio file metadata utilities for M4B/MP4 tag extraction.
Used by library scanner and importer modules.
"""
from typing import Optional


def get_mp4_tag(audio_file, tag_name: str) -> Optional[str]:
    """
    Get MP4 tag value safely from audio file.

    Args:
        audio_file: Mutagen MP4 audio file object
        tag_name: Tag name to extract (e.g., '\xa9nam' for title, '\xa9ART' for artist)

    Returns:
        Tag value as string, or None if tag doesn't exist or can't be decoded
    """
    try:
        tag_value = audio_file.get(tag_name)
        if tag_value:
            if isinstance(tag_value[0], bytes):
                return tag_value[0].decode('utf-8')
            return str(tag_value[0])
    except (IndexError, AttributeError, UnicodeDecodeError):
        pass
    return None
