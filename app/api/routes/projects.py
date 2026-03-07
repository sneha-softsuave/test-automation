"""API routes for project management (Generate Test Case module)."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from pathlib import Path
import json
import re
import shutil
from datetime import datetime

router = APIRouter(prefix="/projects", tags=["Projects"])

PROJECTS_DIR = Path("projects")


def sanitize_name(name: str) -> str:
    """Sanitize project name: spaces to underscores, strip special chars."""
    name = name.strip()
    name = name.replace(" ", "_")
    name = re.sub(r"[^\w\-]", "", name)
    return name


class ProjectCreate(BaseModel):
    name: str


class SaveTestRequest(BaseModel):
    suite: dict


@router.get("/", response_model=List[dict])
async def list_projects():
    """List all projects with test count."""
    PROJECTS_DIR.mkdir(exist_ok=True)
    projects = []
    for folder in sorted(PROJECTS_DIR.iterdir()):
        if folder.is_dir():
            test_count = len(list(folder.glob("*.json")))
            projects.append({"name": folder.name, "test_count": test_count})
    return projects


@router.post("/", status_code=201)
async def create_project(body: ProjectCreate):
    """Create a new project folder."""
    PROJECTS_DIR.mkdir(exist_ok=True)
    safe_name = sanitize_name(body.name)
    if not safe_name:
        raise HTTPException(status_code=400, detail="Invalid project name")
    project_dir = PROJECTS_DIR / safe_name
    if project_dir.exists():
        raise HTTPException(status_code=409, detail=f"Project '{safe_name}' already exists")
    project_dir.mkdir()
    return {"name": safe_name}


@router.get("/{name}/tests", response_model=List[dict])
async def list_project_tests(name: str):
    """List all saved tests in a project."""
    PROJECTS_DIR.mkdir(exist_ok=True)
    project_dir = PROJECTS_DIR / name
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
    tests = []
    for f in sorted(project_dir.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text())
            base_url = data.get("base_url", "")
            test_case_count = len(data.get("test_cases", []))
        except Exception:
            base_url = ""
            test_case_count = 0
        # Extract timestamp from filename: {name}_{YYYY-MM-DD}_{HH-MM-SS}.json
        stem = f.stem
        prefix = f"{name}_"
        saved_at = stem[len(prefix):] if stem.startswith(prefix) else stem
        tests.append({
            "filename": f.name,
            "saved_at": saved_at,
            "base_url": base_url,
            "test_case_count": test_case_count,
        })
    return tests


@router.post("/{name}/tests", status_code=201)
async def save_test(name: str, body: SaveTestRequest):
    """Save a test suite JSON to a project."""
    PROJECTS_DIR.mkdir(exist_ok=True)
    project_dir = PROJECTS_DIR / name
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{name}_{timestamp}.json"
    file_path = project_dir / filename
    file_path.write_text(json.dumps(body.suite, indent=2))
    return {"filename": filename, "name": name}


@router.get("/{name}/tests/{filename}")
async def load_test(name: str, filename: str):
    """Load a saved test suite JSON."""
    PROJECTS_DIR.mkdir(exist_ok=True)
    file_path = PROJECTS_DIR / name / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Test file not found")
    return json.loads(file_path.read_text())


@router.delete("/{name}/tests/{filename}", status_code=204)
async def delete_test(name: str, filename: str):
    """Delete a saved test file."""
    file_path = PROJECTS_DIR / name / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Test file not found")
    file_path.unlink()


@router.delete("/{name}", status_code=204)
async def delete_project(name: str):
    """Delete a project folder and all its tests."""
    project_dir = PROJECTS_DIR / name
    if not project_dir.exists():
        raise HTTPException(status_code=404, detail=f"Project '{name}' not found")
    shutil.rmtree(project_dir)
