"""Persistent Jupyter kernel & workspace manager for data analysis projects.

Unlike JupyterCodeExecuter (which creates and destroys kernels per execution),
JupyterSessionManager maintains persistent kernels per project so that
variable state is preserved across multiple chat messages.
"""

import base64
import logging
from pathlib import Path
from typing import Optional

import aiohttp
import websockets
from open_webui.env import SRC_LOG_LEVELS
from open_webui.utils.code_interpreter import ResultModel, execute_in_kernel

logger = logging.getLogger(__name__)
logger.setLevel(SRC_LOG_LEVELS["MAIN"])

DATA_ANALYSIS_ALLOWED_EXTENSIONS = {"csv", "xlsx", "xls", "tsv", "parquet"}


class JupyterSessionManager:
    """Manage persistent Jupyter kernels and file workspaces for projects."""

    def __init__(
        self,
        base_url: str,
        token: str = "",
        password: str = "",
        timeout: int = 60,
    ):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.password = password
        self.timeout = timeout

    def _params(self) -> dict:
        return {"token": self.token} if self.token else {}

    async def _get_session(self) -> aiohttp.ClientSession:
        session = aiohttp.ClientSession(base_url=self.base_url)
        if self.password and not self.token:
            async with session.get("/login") as response:
                response.raise_for_status()
                xsrf_token = response.cookies["_xsrf"].value
                session.cookie_jar.update_cookies(response.cookies)
                session.headers.update({"X-XSRFToken": xsrf_token})
            async with session.post(
                "/login",
                data={"_xsrf": xsrf_token, "password": self.password},
                allow_redirects=False,
            ) as response:
                response.raise_for_status()
                session.cookie_jar.update_cookies(response.cookies)
        return session

    # ──────────────────────────────────────
    # Kernel lifecycle
    # ──────────────────────────────────────

    async def ensure_kernel(
        self, project_id: str, stored_kernel_id: Optional[str] = None
    ) -> str:
        """Return a live kernel ID, reusing stored_kernel_id if still alive.

        New kernels are sandboxed to only access workspace/{project_id}/.
        When a new kernel is created (container restart etc.), project files
        are automatically re-mounted from Storage.
        """
        is_new_kernel = False
        session = await self._get_session()
        try:
            if stored_kernel_id:
                async with session.get(
                    f"/api/kernels/{stored_kernel_id}", params=self._params()
                ) as resp:
                    if resp.ok:
                        # Kernel alive — ensure sandbox + files
                        await self._ensure_files_mounted(session, project_id)
                        await self._apply_sandbox(stored_kernel_id, project_id)
                        return stored_kernel_id
                    logger.warning(
                        "Kernel %s is dead, creating new one", stored_kernel_id
                    )
            # Create new kernel
            async with session.post("/api/kernels", params=self._params()) as resp:
                resp.raise_for_status()
                data = await resp.json()
                kernel_id = data["id"]
                is_new_kernel = True
                logger.info("Created new Jupyter kernel: %s", kernel_id)
        finally:
            await session.close()

        # Sandbox: restrict file access to this project's workspace only
        await self._apply_sandbox(kernel_id, project_id)

        # Re-mount project files (container may have restarted)
        if is_new_kernel:
            await self._remount_project_files(project_id)

        return kernel_id

    async def _ensure_files_mounted(
        self, session: aiohttp.ClientSession, project_id: str
    ) -> None:
        """Check if workspace directory exists, re-mount files if missing."""
        jupyter_path = f"workspace/{project_id}"
        async with session.get(
            f"/api/contents/{jupyter_path}", params=self._params()
        ) as resp:
            if resp.ok:
                data = await resp.json()
                if data.get("content"):
                    return  # Files exist
        # Workspace missing — re-mount
        logger.info("Workspace missing for %s, re-mounting files", project_id)
        await self._remount_project_files(project_id)

    async def _remount_project_files(self, project_id: str) -> None:
        """Re-mount all project files from Storage to Jupyter workspace."""
        from open_webui.models.files import Files
        from open_webui.models.knowledge import Knowledges
        from open_webui.models.projects import Projects

        project = Projects.get_project_by_id(project_id)
        if not project or not project.knowledge_id:
            return

        knowledge = Knowledges.get_knowledge_by_id(project.knowledge_id)
        if not knowledge or not knowledge.data:
            return

        file_ids = knowledge.data.get("file_ids", [])
        for file_id in file_ids:
            file = Files.get_file_by_id(file_id)
            if file:
                success = await self.upload_file(project_id, file.filename, file.path)
                if success:
                    logger.info(
                        "Re-mounted %s to workspace/%s", file.filename, project_id
                    )
                else:
                    logger.warning("Failed to re-mount %s", file.filename)

    async def _apply_sandbox(self, kernel_id: str, project_id: str) -> None:
        """Run security preamble to restrict file access to project workspace."""
        sandbox_code = f"""
import os as _os

# Set working directory to project workspace (absolute path from home)
_HOME = _os.path.expanduser('~')
_WORKSPACE = _os.path.join(_HOME, 'workspace', '{project_id}')
_os.makedirs(_WORKSPACE, exist_ok=True)
_os.chdir(_WORKSPACE)

# Restrict pandas file read functions to workspace only
# (builtins.open is NOT overridden — libraries like plotly need to read internal files)
def _check_path(filepath):
    if isinstance(filepath, (str, _os.PathLike)):
        resolved = _os.path.realpath(_os.path.join(_os.getcwd(), str(filepath)))
        if not resolved.startswith(_WORKSPACE):
            raise PermissionError(
                f"Access denied: file access is restricted to the project workspace. Attempted: {{filepath}}"
            )

try:
    import pandas as _pd
    for _fn_name in ['read_csv', 'read_excel', 'read_parquet', 'read_json', 'read_table']:
        _orig = getattr(_pd, _fn_name)
        def _make_restricted(_orig_fn):
            def _restricted(filepath_or_buffer, *args, **kwargs):
                _check_path(filepath_or_buffer)
                return _orig_fn(filepath_or_buffer, *args, **kwargs)
            return _restricted
        setattr(_pd, _fn_name, _make_restricted(_orig))
except ImportError:
    pass

print(f"Sandbox active: {{_WORKSPACE}}")
"""
        try:
            result = await self.execute_code(kernel_id, sandbox_code)
            if result.stderr:
                logger.warning("Sandbox setup warning: %s", result.stderr[:200])
            else:
                logger.info(
                    "Kernel %s sandboxed to workspace/%s", kernel_id, project_id
                )
        except Exception as e:
            logger.error("Failed to apply sandbox to kernel %s: %s", kernel_id, e)

    async def delete_kernel(self, kernel_id: str) -> None:
        """Delete a kernel."""
        session = await self._get_session()
        try:
            async with session.delete(
                f"/api/kernels/{kernel_id}", params=self._params()
            ) as resp:
                if resp.ok:
                    logger.info("Deleted kernel %s", kernel_id)
                else:
                    logger.warning(
                        "Failed to delete kernel %s: %s", kernel_id, resp.status
                    )
        finally:
            await session.close()

    # ──────────────────────────────────────
    # File workspace management
    # ──────────────────────────────────────

    async def upload_file(self, project_id: str, filename: str, file_path: str) -> bool:
        """Upload a file to the Jupyter workspace at /workspace/{project_id}/{filename}.

        Uses Storage provider to read the file, so it works with local, S3, Azure, GCS.
        """
        try:
            from open_webui.storage.provider import Storage

            resolved_path = Storage.get_file(file_path)
            file_bytes = Path(resolved_path).read_bytes()
        except Exception as e:
            logger.error("Failed to read file via Storage: %s (path=%s)", e, file_path)
            return False

        content_b64 = base64.b64encode(file_bytes).decode("utf-8")
        jupyter_path = f"workspace/{project_id}/{filename}"

        session = await self._get_session()
        try:
            # Ensure directory exists
            await self._ensure_directory(session, f"workspace/{project_id}")

            async with session.put(
                f"/api/contents/{jupyter_path}",
                params=self._params(),
                json={
                    "type": "file",
                    "format": "base64",
                    "content": content_b64,
                },
            ) as resp:
                if resp.ok:
                    logger.info("Uploaded %s to Jupyter workspace", jupyter_path)
                    return True
                error = await resp.text()
                logger.error("Failed to upload %s: %s", jupyter_path, error)
                return False
        finally:
            await session.close()

    async def remove_file(self, project_id: str, filename: str) -> bool:
        """Remove a file from the Jupyter workspace."""
        jupyter_path = f"workspace/{project_id}/{filename}"
        session = await self._get_session()
        try:
            async with session.delete(
                f"/api/contents/{jupyter_path}", params=self._params()
            ) as resp:
                return resp.ok
        finally:
            await session.close()

    async def cleanup_workspace(self, project_id: str) -> None:
        """Delete the entire project workspace directory."""
        jupyter_path = f"workspace/{project_id}"
        session = await self._get_session()
        try:
            async with session.delete(
                f"/api/contents/{jupyter_path}", params=self._params()
            ) as resp:
                if resp.ok:
                    logger.info("Cleaned up workspace %s", jupyter_path)
        finally:
            await session.close()

    async def _ensure_directory(
        self, session: aiohttp.ClientSession, dir_path: str
    ) -> None:
        """Create directory tree in Jupyter (parent directories first)."""
        parts = dir_path.split("/")
        for i in range(1, len(parts) + 1):
            partial = "/".join(parts[:i])
            async with session.put(
                f"/api/contents/{partial}",
                params=self._params(),
                json={"type": "directory"},
            ) as resp:
                pass  # OK if already exists (409) or created (201)

    # ──────────────────────────────────────
    # Code execution
    # ──────────────────────────────────────

    async def execute_code(self, kernel_id: str, code: str) -> ResultModel:
        """Execute code in an existing persistent kernel."""
        session = await self._get_session()
        try:
            ws_url, ws_headers = self._build_ws(kernel_id, session)
            async with websockets.connect(ws_url, additional_headers=ws_headers) as ws:
                return await execute_in_kernel(ws, code, self.timeout)
        finally:
            await session.close()

    def _build_ws(
        self, kernel_id: str, session: aiohttp.ClientSession
    ) -> tuple[str, dict]:
        ws_base = self.base_url.replace("http", "ws")
        params = self._params()
        ws_params = (
            "?" + "&".join(f"{k}={v}" for k, v in params.items()) if params else ""
        )
        ws_url = f"{ws_base}/api/kernels/{kernel_id}/channels{ws_params}"
        ws_headers = {}
        if self.password and not self.token:
            ws_headers = {
                "Cookie": "; ".join(f"{c.key}={c.value}" for c in session.cookie_jar),
                **session.headers,
            }
        return ws_url, ws_headers

    # ──────────────────────────────────────
    # Metadata extraction
    # ──────────────────────────────────────

    async def extract_file_metadata(
        self, kernel_id: str, project_id: str, filename: str
    ) -> dict:
        """Execute pandas code in the kernel to extract file metadata."""
        ext = filename.rsplit(".", 1)[-1].lower()
        if ext == "csv" or ext == "tsv":
            sep = "," if ext == "csv" else "\\t"
            read_cmd = f"pd.read_csv(filepath, sep='{sep}')"
        elif ext in ("xlsx", "xls"):
            read_cmd = "pd.read_excel(filepath)"
        elif ext == "parquet":
            read_cmd = "pd.read_parquet(filepath)"
        else:
            return {"error": f"Unsupported file type: {ext}"}

        # Excel: also extract sheet names
        sheet_code = ""
        if ext in ("xlsx", "xls"):
            sheet_code = """
xf = pd.ExcelFile(filepath)
metadata["sheets"] = xf.sheet_names
metadata["sheet_row_counts"] = {s: len(pd.read_excel(filepath, sheet_name=s)) for s in xf.sheet_names}
"""

        code = f"""
import pandas as pd
import json

filepath = '{filename}'
df = {read_cmd}

# Column details: dtype, unique count, null count, sample values
column_details = {{}}
for col in df.columns:
    sample_vals = df[col].dropna().unique()[:5].tolist()
    sample_vals = [str(v) for v in sample_vals]
    column_details[col] = {{
        "dtype": str(df[col].dtype),
        "unique_count": int(df[col].nunique()),
        "null_count": int(df[col].isnull().sum()),
        "sample_values": sample_vals,
    }}

metadata = {{
    "filename": "{filename}",
    "columns": df.columns.tolist(),
    "dtypes": {{col: str(dtype) for col, dtype in df.dtypes.items()}},
    "row_count": len(df),
    "column_details": column_details,
    "sample_markdown": df.head(3).to_markdown(index=False),
}}
{sheet_code}
print("__METADATA__" + json.dumps(metadata, ensure_ascii=False))
"""
        result = await self.execute_code(kernel_id, code)

        # Parse metadata from stdout
        for line in (result.stdout or "").split("\n"):
            if line.startswith("__METADATA__"):
                import json

                return json.loads(line[len("__METADATA__") :])

        return {
            "filename": filename,
            "error": result.stderr or "Failed to extract metadata",
        }


def extract_file_metadata_local(file_path: str, filename: str) -> dict:
    """Extract metadata without Jupyter (for Pyodide engine fallback).

    Uses Storage provider + pandas directly in the backend process.
    """
    import pandas as pd
    from open_webui.storage.provider import Storage

    try:
        resolved_path = Storage.get_file(file_path)
    except Exception as e:
        return {"filename": filename, "error": f"Storage read failed: {e}"}

    ext = filename.rsplit(".", 1)[-1].lower()
    try:
        if ext == "csv":
            df = pd.read_csv(resolved_path)
        elif ext == "tsv":
            df = pd.read_csv(resolved_path, sep="\t")
        elif ext in ("xlsx", "xls"):
            df = pd.read_excel(resolved_path)
        elif ext == "parquet":
            df = pd.read_parquet(resolved_path)
        else:
            return {"filename": filename, "error": f"Unsupported: {ext}"}

        column_details = {}
        for col in df.columns:
            sample_vals = df[col].dropna().unique()[:5].tolist()
            sample_vals = [str(v) for v in sample_vals]
            column_details[col] = {
                "dtype": str(df[col].dtype),
                "unique_count": int(df[col].nunique()),
                "null_count": int(df[col].isnull().sum()),
                "sample_values": sample_vals,
            }

        result = {
            "filename": filename,
            "columns": df.columns.tolist(),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "row_count": len(df),
            "column_details": column_details,
            "sample_markdown": df.head(3).to_markdown(index=False),
        }

        # Excel: sheet info
        if ext in ("xlsx", "xls"):
            xf = pd.ExcelFile(resolved_path)
            result["sheets"] = xf.sheet_names
            result["sheet_row_counts"] = {
                s: len(pd.read_excel(resolved_path, sheet_name=s))
                for s in xf.sheet_names
            }

        return result
    except Exception as e:
        return {"filename": filename, "error": str(e)}
