"""
AudioConverter service for handling AAX to M4B conversion.

This service is responsible for:
- FFmpeg availability checking
- Quality setting validation
- AAX to M4B conversion using FFmpeg with decryption keys
"""

import asyncio
import subprocess
import json
from pathlib import Path
from typing import Optional


class AudioConverter:
    """
    Handles audio file conversion from AAX to M4B format using FFmpeg.
    """

    @staticmethod
    def check_ffmpeg():
        """
        Verify that FFmpeg is installed and accessible.

        Raises:
            Exception: If FFmpeg is not found or not executable
        """
        try:
            subprocess.run(
                ['ffmpeg', '-version'],
                capture_output=True,
                text=True,
                check=True,
                timeout=10
            )
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
            raise Exception("FFmpeg not found or not executable. Please install FFmpeg.")

    @staticmethod
    def validate_quality_setting(quality: str) -> str:
        """
        Validate and normalize quality setting.

        Args:
            quality: Quality string (e.g., 'extreme', 'high', 'normal', 'standard')

        Returns:
            Normalized quality ('High' or 'Normal')
        """
        quality_map = {
            "extreme": "High",
            "high": "High",
            "normal": "Normal",
            "standard": "Normal"
        }
        normalized_quality = quality_map.get(quality.lower(), quality)
        if normalized_quality not in ["High", "Normal"]:
            print(f"⚠️  Invalid quality '{quality}'. Using 'High'.")
            return "High"
        return normalized_quality

    async def convert_to_m4b(
        self,
        aaxc_file: Path,
        m4b_file: Path,
        simple_voucher_file: Optional[Path] = None
    ) -> None:
        """
        Convert AAX file to M4B format using FFmpeg.

        Args:
            aaxc_file: Path to source AAX/AAXC file
            m4b_file: Path to destination M4B file
            simple_voucher_file: Optional path to decrypted voucher file
                               (defaults to {aaxc_stem}_simple.json in same directory)

        Raises:
            Exception: If FFmpeg is not available or conversion fails
        """
        self.check_ffmpeg()

        # Default voucher file location if not provided
        if simple_voucher_file is None:
            simple_voucher_file = aaxc_file.with_suffix('.json').with_name(
                aaxc_file.stem + '_simple.json'
            )

        if not simple_voucher_file.exists():
            raise Exception(f"Decrypted voucher file not found: {simple_voucher_file}")

        try:
            voucher_data = json.loads(simple_voucher_file.read_text())
            key = voucher_data["key"]
            iv = voucher_data["iv"]
        except (KeyError, json.JSONDecodeError) as e:
            raise Exception(f"Could not read key/iv from voucher file: {e}")

        cmd = [
            'ffmpeg', '-v', 'quiet', '-stats', '-y',
            '-audible_key', key, '-audible_iv', iv,
            '-i', str(aaxc_file), '-c', 'copy', str(m4b_file)
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await process.communicate()
            if process.returncode != 0:
                raise Exception(f"FFmpeg conversion failed: {stderr.decode()}")
        except Exception as e:
            # Clean up partial output file on failure
            if m4b_file.exists():
                m4b_file.unlink()
            raise e
