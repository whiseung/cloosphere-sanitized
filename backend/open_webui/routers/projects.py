import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from open_webui.constants import ERROR_MESSAGES
from open_webui.env import SRC_LOG_LEVELS
from open_webui.models.chats import Chats
from open_webui.models.files import Files
from open_webui.models.knowledge import (
    KnowledgeForm,
    Knowledges,
)
from open_webui.models.projects import (
    ProjectForm,
    ProjectModel,
    Projects,
    ProjectUpdateForm,
    ProjectUserModel,
)
from open_webui.models.users import Users
from open_webui.retrieval.knowledge_service import SearchEngineKnowledge
from open_webui.routers.knowledge import (
    KnowledgeFileIdForm,
    add_file_to_knowledge_by_id,
    remove_file_from_knowledge_by_id,
)
from open_webui.routers.retrieval import ProcessFileForm, process_file
from open_webui.utils.access_control import has_access
from open_webui.utils.auth import get_verified_user
from open_webui.utils.jupyter_session import (
    DATA_ANALYSIS_ALLOWED_EXTENSIONS,
    JupyterSessionManager,
    extract_file_metadata_local,
)
from pydantic import BaseModel

log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS["MODELS"])

router = APIRouter()


############################
# Response Models
############################


class ProjectResponse(ProjectUserModel):
    files: Optional[list] = None


class ProjectChatResponse(BaseModel):
    id: str
    title: str
    preview: str = ""
    updated_at: int
    created_at: int


class ProjectShareForm(BaseModel):
    user_ids: list[str] = []


class ProjectShareResponse(BaseModel):
    copied_count: int
    copied_project_ids: list[str]


############################
# getProjects
############################


@router.get("/", response_model=list[ProjectResponse])
async def get_projects(user=Depends(get_verified_user)):
    projects = Projects.get_projects_by_user_id(user.id, "read")

    project_responses = []
    for project in projects:
        files = []
        if project.knowledge_id:
            knowledge = Knowledges.get_knowledge_by_id(project.knowledge_id)
            if knowledge and knowledge.data:
                file_ids = knowledge.data.get("file_ids", [])
                files = Files.get_file_metadatas_by_ids(file_ids)

        project_responses.append(
            ProjectResponse(
                **project.model_dump(),
                files=files,
            )
        )

    return project_responses


############################
# CreateNewProject
############################


@router.post("/create", response_model=Optional[ProjectResponse])
async def create_new_project(
    request: Request,
    form_data: ProjectForm,
    user=Depends(get_verified_user),
):
    if Projects.name_exists(form_data.name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NAME_TAKEN,
        )

    # 1. Create Knowledge Base for the project
    kb = Knowledges.insert_new_knowledge(
        user.id,
        KnowledgeForm(
            name=f"[Project] {form_data.name}",
            description=f"Knowledge base for project: {form_data.name}",
            access_control=form_data.access_control,
        ),
    )

    if not kb:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to create knowledge base"),
        )

    # 2. Create Project with knowledge_id
    project = Projects.insert_new_project(user.id, form_data, knowledge_id=kb.id)

    if project:
        return ProjectResponse(**project.model_dump(), files=[])
    else:
        # Rollback: delete the created KB
        Knowledges.delete_knowledge_by_id(kb.id)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to create project"),
        )


############################
# GetProjectById
############################


@router.get("/{id}", response_model=Optional[ProjectResponse])
async def get_project_by_id(id: str, user=Depends(get_verified_user)):
    project = Projects.get_project_by_id(id=id)

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        user.role != "admin"
        and project.user_id != user.id
        and not has_access(user.id, "read", project.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    files = []
    if project.knowledge_id:
        knowledge = Knowledges.get_knowledge_by_id(project.knowledge_id)
        if knowledge and knowledge.data:
            file_ids = knowledge.data.get("file_ids", [])
            files = Files.get_files_by_ids(file_ids)

    user_info = None
    u = Users.get_user_by_id(project.user_id)
    if u:
        user_info = u.model_dump()

    return ProjectResponse(
        **project.model_dump(),
        files=files,
        user=user_info,
    )


############################
# GetProjectChats
############################


@router.get("/{id}/chats", response_model=list[ProjectChatResponse])
async def get_project_chats(id: str, user=Depends(get_verified_user)):
    project = Projects.get_project_by_id(id=id)

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        user.role != "admin"
        and project.user_id != user.id
        and not has_access(user.id, "read", project.access_control)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    chat_ids = (project.data or {}).get("chat_ids", [])
    if not chat_ids:
        return []

    chats = Chats.get_chat_list_by_chat_ids(chat_ids)
    results = []
    for chat in chats:
        preview = ""
        try:
            messages = chat.chat.get("messages", {})
            # Find first user message for preview
            for msg in messages.values():
                if msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        content = " ".join(
                            p.get("text", "")
                            for p in content
                            if isinstance(p, dict) and p.get("type") == "text"
                        )
                    preview = content[:150] if content else ""
                    break
        except Exception:
            pass

        results.append(
            ProjectChatResponse(
                id=chat.id,
                title=chat.title,
                preview=preview,
                updated_at=chat.updated_at,
                created_at=chat.created_at,
            )
        )
    return results


############################
# UpdateProjectById
############################


@router.post("/{id}/update", response_model=Optional[ProjectResponse])
async def update_project_by_id(
    id: str,
    form_data: ProjectUpdateForm,
    user=Depends(get_verified_user),
):
    project = Projects.get_project_by_id(id=id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        project.user_id != user.id
        and not has_access(user.id, "write", project.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if form_data.name and Projects.name_exists(form_data.name, exclude_id=id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.NAME_TAKEN,
        )

    project = Projects.update_project_by_id(id=id, form_data=form_data)

    if not project:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Failed to update project"),
        )

    # Sync KB name/access_control if changed
    if project.knowledge_id and (
        form_data.name is not None or form_data.access_control is not None
    ):
        kb_update = KnowledgeForm(
            name=f"[Project] {project.name}",
            description=f"Knowledge base for project: {project.name}",
            access_control=project.access_control,
        )
        Knowledges.update_knowledge_by_id(project.knowledge_id, kb_update)

    files = []
    if project.knowledge_id:
        knowledge = Knowledges.get_knowledge_by_id(project.knowledge_id)
        if knowledge and knowledge.data:
            file_ids = knowledge.data.get("file_ids", [])
            files = Files.get_files_by_ids(file_ids)

    return ProjectResponse(**project.model_dump(), files=files)


############################
# DeleteProjectById
############################


@router.delete("/{id}/delete", response_model=bool)
async def delete_project_by_id(
    request: Request, id: str, user=Depends(get_verified_user)
):
    project = Projects.get_project_by_id(id=id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        project.user_id != user.id
        and not has_access(user.id, "write", project.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    # Cleanup Jupyter resources for data_analysis projects
    if project.type == "data_analysis":
        try:
            engine = request.app.state.config.CODE_EXECUTION_ENGINE
            if (
                engine == "jupyter"
                and request.app.state.config.CODE_EXECUTION_JUPYTER_URL
            ):
                mgr = _get_jupyter_manager(request)
                kernel_id = (project.data or {}).get("jupyter_kernel_id")
                if kernel_id:
                    await mgr.delete_kernel(kernel_id)
                await mgr.cleanup_workspace(project.id)
        except Exception as e:
            log.warning(f"Failed to cleanup Jupyter for project {id}: {e}")

    # Delete associated Knowledge Base and its vector data
    if project.knowledge_id:
        if project.type != "data_analysis":
            # Only delete vectors for general projects (data_analysis has none)
            try:
                knowledge_svc = SearchEngineKnowledge(
                    app=request.app, collection_name=project.knowledge_id
                )
                await knowledge_svc.delete_by_collection()
            except Exception as e:
                log.error(f"Failed to delete knowledge vectors for project {id}: {e}")

        Knowledges.delete_knowledge_by_id(project.knowledge_id)

    # Delete associated chats
    chat_ids = (project.data or {}).get("chat_ids", [])
    for chat_id in chat_ids:
        try:
            Chats.delete_chat_by_id(chat_id)
        except Exception as e:
            log.error(f"Failed to delete chat {chat_id} for project {id}: {e}")

    return Projects.delete_project_by_id(id=id)


############################
# AddFileToProject
############################


@router.post("/{id}/file/add")
async def add_file_to_project(
    request: Request,
    id: str,
    form_data: KnowledgeFileIdForm,
    user=Depends(get_verified_user),
):
    project = Projects.get_project_by_id(id=id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        project.user_id != user.id
        and not has_access(user.id, "write", project.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if not project.knowledge_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Project has no knowledge base"),
        )

    if project.type == "data_analysis":
        return await _add_data_file_to_project(request, project, form_data)
    else:
        # Delegate to knowledge router (RAG pipeline)
        return await add_file_to_knowledge_by_id(
            request, project.knowledge_id, form_data, user
        )


async def _add_data_file_to_project(
    request: Request, project: ProjectModel, form_data: KnowledgeFileIdForm
):
    """Add a data file to a data_analysis project (skip RAG, extract metadata)."""
    file = Files.get_file_by_id(form_data.file_id)
    if not file:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    # Validate file extension
    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in DATA_ANALYSIS_ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only data files are allowed ({', '.join(sorted(DATA_ANALYSIS_ALLOWED_EXTENSIONS))}). Got: .{ext}",
        )

    # Add file_id to Knowledge (for file list tracking, no RAG processing)
    Knowledges.add_file_id_to_knowledge(project.knowledge_id, form_data.file_id)

    # Extract metadata and optionally mount to Jupyter
    engine = request.app.state.config.CODE_EXECUTION_ENGINE
    file_path = file.path

    if engine == "jupyter" and request.app.state.config.CODE_EXECUTION_JUPYTER_URL:
        # Jupyter: mount file + extract metadata via kernel
        mgr = _get_jupyter_manager(request)
        stored_kernel_id = (project.data or {}).get("jupyter_kernel_id")
        kernel_id = await mgr.ensure_kernel(project.id, stored_kernel_id)

        # Store kernel_id if new
        if kernel_id != stored_kernel_id:
            Projects.update_project_data(project.id, {"jupyter_kernel_id": kernel_id})

        await mgr.upload_file(project.id, file.filename, file_path)
        metadata = await mgr.extract_file_metadata(kernel_id, project.id, file.filename)
    else:
        # Pyodide or no Jupyter: extract metadata locally
        metadata = extract_file_metadata_local(file_path, file.filename)

    # Store metadata in project.data
    file_metadata = (project.data or {}).get("file_metadata", {})
    file_metadata[form_data.file_id] = metadata
    Projects.update_project_data(project.id, {"file_metadata": file_metadata})

    # Return updated project
    updated_project = Projects.get_project_by_id(project.id)
    knowledge = Knowledges.get_knowledge_by_id(project.knowledge_id)
    files = []
    if knowledge and knowledge.data:
        file_ids = knowledge.data.get("file_ids", [])
        files = Files.get_files_by_ids(file_ids)
    return ProjectResponse(**updated_project.model_dump(), files=files)


def _get_jupyter_manager(request: Request) -> JupyterSessionManager:
    return JupyterSessionManager(
        base_url=request.app.state.config.CODE_EXECUTION_JUPYTER_URL,
        token=request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_TOKEN,
        password=request.app.state.config.CODE_EXECUTION_JUPYTER_AUTH_PASSWORD,
        timeout=request.app.state.config.CODE_EXECUTION_JUPYTER_TIMEOUT,
    )


############################
# RemoveFileFromProject
############################


@router.post("/{id}/file/remove")
async def remove_file_from_project(
    request: Request,
    id: str,
    form_data: KnowledgeFileIdForm,
    user=Depends(get_verified_user),
):
    project = Projects.get_project_by_id(id=id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        project.user_id != user.id
        and not has_access(user.id, "write", project.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if not project.knowledge_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("Project has no knowledge base"),
        )

    if project.type == "data_analysis":
        return await _remove_data_file_from_project(request, project, form_data)
    else:
        return await remove_file_from_knowledge_by_id(
            request, project.knowledge_id, form_data, user
        )


async def _remove_data_file_from_project(
    request: Request, project: ProjectModel, form_data: KnowledgeFileIdForm
):
    """Remove a data file from a data_analysis project."""
    file = Files.get_file_by_id(form_data.file_id)

    # Remove from Knowledge file list
    knowledge = Knowledges.get_knowledge_by_id(project.knowledge_id)
    if knowledge and knowledge.data:
        file_ids = knowledge.data.get("file_ids", [])
        if form_data.file_id in file_ids:
            file_ids.remove(form_data.file_id)
            Knowledges.update_knowledge_data_by_id(
                id=project.knowledge_id, data={**knowledge.data, "file_ids": file_ids}
            )

    # Remove from Jupyter workspace
    engine = request.app.state.config.CODE_EXECUTION_ENGINE
    if (
        engine == "jupyter"
        and request.app.state.config.CODE_EXECUTION_JUPYTER_URL
        and file
    ):
        try:
            mgr = _get_jupyter_manager(request)
            await mgr.remove_file(project.id, file.filename)
        except Exception as e:
            log.warning(f"Failed to remove file from Jupyter workspace: {e}")

    # Remove from file_metadata
    file_metadata = (project.data or {}).get("file_metadata", {})
    file_metadata.pop(form_data.file_id, None)
    Projects.update_project_data(project.id, {"file_metadata": file_metadata})

    updated_project = Projects.get_project_by_id(project.id)
    knowledge = Knowledges.get_knowledge_by_id(project.knowledge_id)
    files = []
    if knowledge and knowledge.data:
        file_ids = knowledge.data.get("file_ids", [])
        files = Files.get_files_by_ids(file_ids)
    return ProjectResponse(**updated_project.model_dump(), files=files)


############################
# ExecuteCodeInProject
############################


class ProjectCodeForm(BaseModel):
    code: str


@router.post("/{id}/code/execute")
async def execute_project_code(
    request: Request,
    id: str,
    form_data: ProjectCodeForm,
    user=Depends(get_verified_user),
):
    """Execute Python code in a data_analysis project's Jupyter kernel."""
    project = Projects.get_project_by_id(id=id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if project.type != "data_analysis":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Code execution is only available for data analysis projects",
        )

    if (
        project.user_id != user.id
        and not has_access(user.id, "write", project.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    engine = request.app.state.config.CODE_EXECUTION_ENGINE
    if engine != "jupyter" or not request.app.state.config.CODE_EXECUTION_JUPYTER_URL:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Jupyter engine is required for data analysis code execution. Configure it in Admin > Settings > Code Execution.",
        )

    mgr = _get_jupyter_manager(request)
    stored_kernel_id = (project.data or {}).get("jupyter_kernel_id")
    kernel_id = await mgr.ensure_kernel(project.id, stored_kernel_id)

    if kernel_id != stored_kernel_id:
        Projects.update_project_data(project.id, {"jupyter_kernel_id": kernel_id})

    result = await mgr.execute_code(kernel_id, form_data.code)
    return result.model_dump()


############################
# AddChatToProject
############################


class ProjectChatIdForm(BaseModel):
    chat_id: str


@router.post("/{id}/chat/add", response_model=Optional[ProjectModel])
async def add_chat_to_project(
    id: str,
    form_data: ProjectChatIdForm,
    user=Depends(get_verified_user),
):
    project = Projects.get_project_by_id(id=id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        project.user_id != user.id
        and not has_access(user.id, "write", project.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    project = Projects.add_chat_id_to_project(id=id, chat_id=form_data.chat_id)
    if project:
        return project
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Failed to add chat to project"),
    )


############################
# RemoveChatFromProject
############################


@router.post("/{id}/chat/remove", response_model=Optional[ProjectModel])
async def remove_chat_from_project(
    id: str,
    form_data: ProjectChatIdForm,
    user=Depends(get_verified_user),
):
    project = Projects.get_project_by_id(id=id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if (
        project.user_id != user.id
        and not has_access(user.id, "write", project.access_control)
        and user.role != "admin"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    project = Projects.remove_chat_id_from_project(id=id, chat_id=form_data.chat_id)
    if project:
        return project
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=ERROR_MESSAGES.DEFAULT("Failed to remove chat from project"),
    )


############################
# ShareProject (copy-based)
############################


@router.post("/{id}/share", response_model=ProjectShareResponse)
async def share_project(
    request: Request,
    id: str,
    form_data: ProjectShareForm,
    user=Depends(get_verified_user),
):
    project = Projects.get_project_by_id(id=id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_MESSAGES.NOT_FOUND,
        )

    if project.user_id != user.id and user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ERROR_MESSAGES.ACCESS_PROHIBITED,
        )

    if not form_data.user_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_MESSAGES.DEFAULT("No users specified"),
        )

    # Get source owner info
    owner = Users.get_user_by_id(project.user_id)
    owner_name = owner.name if owner else "Unknown"

    # Get source KB file_ids
    source_file_ids: list[str] = []
    if project.knowledge_id:
        kb = Knowledges.get_knowledge_by_id(project.knowledge_id)
        if kb and kb.data:
            source_file_ids = kb.data.get("file_ids", [])

    copied_project_ids: list[str] = []

    for target_user_id in form_data.user_ids:
        if target_user_id == project.user_id:
            continue

        target_user = Users.get_user_by_id(target_user_id)
        if not target_user:
            continue

        # 1. Create new KB for the copied project
        new_kb = Knowledges.insert_new_knowledge(
            target_user_id,
            KnowledgeForm(
                name=f"[Project] {project.name}",
                description=f"Knowledge base for project: {project.name}",
            ),
        )
        if not new_kb:
            log.error(f"Failed to create KB for user {target_user_id}")
            continue

        # 2. Create new Project
        copied_meta = dict(project.meta) if project.meta else {}
        copied_meta["copied_from"] = {
            "user_id": project.user_id,
            "user_name": owner_name,
            "project_id": project.id,
            "project_name": project.name,
            "copied_at": int(time.time()),
        }

        new_project = Projects.insert_new_project(
            target_user_id,
            ProjectForm(
                name=project.name,
                description=project.description,
                instructions=project.instructions,
                meta=copied_meta,
            ),
            knowledge_id=new_kb.id,
        )
        if not new_project:
            Knowledges.delete_knowledge_by_id(new_kb.id)
            log.error(f"Failed to create project for user {target_user_id}")
            continue

        # 3. Copy files: re-index vectors into the new KB
        for fid in source_file_ids:
            try:
                await process_file(
                    request,
                    ProcessFileForm(file_id=fid, collection_name=new_kb.id),
                    user=target_user,
                )
                Knowledges.add_file_id_to_knowledge(new_kb.id, fid)
            except Exception as e:
                log.error(f"Failed to copy file {fid} to KB {new_kb.id}: {e}")

        copied_project_ids.append(new_project.id)

    return ProjectShareResponse(
        copied_count=len(copied_project_ids),
        copied_project_ids=copied_project_ids,
    )
