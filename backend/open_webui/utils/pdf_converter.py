import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from open_webui.env import SRC_LOG_LEVELS

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])


def is_libreoffice_available() -> bool:
    """Check if LibreOffice is installed and available."""
    return shutil.which("libreoffice") is not None


def should_convert_to_pdf(filename: str, convert_extensions: list[str]) -> bool:
    """Check if a file should be converted to PDF based on its extension."""
    if not convert_extensions:
        return False
    ext = Path(filename).suffix.lstrip(".").lower()
    return ext in [e.strip().lower() for e in convert_extensions if e.strip()]


def convert_file_to_pdf(input_path: str, timeout: int = 120) -> str:
    """
    Convert a file to PDF using LibreOffice headless mode.

    Args:
        input_path: Path to the input file.
        timeout: Timeout in seconds for the conversion process.

    Returns:
        Path to the converted PDF file.

    Raises:
        RuntimeError: If conversion fails or LibreOffice is not available.
    """
    if not is_libreoffice_available():
        raise RuntimeError("LibreOffice is not installed or not available in PATH")

    input_path = Path(input_path)
    if not input_path.exists():
        raise RuntimeError(f"Input file not found: {input_path}")

    # Use a unique UserInstallation directory to avoid concurrency issues
    user_install_dir = tempfile.mkdtemp(prefix="lo_user_")
    output_dir = tempfile.mkdtemp(prefix="lo_output_")

    try:
        cmd = [
            "libreoffice",
            "--headless",
            "--invisible",
            "--nocrashreport",
            "--nodefault",
            "--nofirststartwizard",
            "--nologo",
            "--norestore",
            f"-env:UserInstallation=file://{user_install_dir}",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(input_path),
        ]

        log.info(f"Converting file to PDF: {input_path.name}")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if result.returncode != 0:
            log.error(f"LibreOffice conversion failed: {result.stderr}")
            raise RuntimeError(
                f"LibreOffice conversion failed (exit code {result.returncode}): {result.stderr}"
            )

        # Find the output PDF file
        pdf_name = input_path.stem + ".pdf"
        pdf_path = Path(output_dir) / pdf_name

        if not pdf_path.exists():
            raise RuntimeError(f"Converted PDF not found at expected path: {pdf_path}")

        log.info(f"Successfully converted to PDF: {pdf_path}")
        return str(pdf_path)

    except subprocess.TimeoutExpired:
        raise RuntimeError(f"LibreOffice conversion timed out after {timeout} seconds")
    finally:
        # Clean up the temporary user installation directory
        shutil.rmtree(user_install_dir, ignore_errors=True)
