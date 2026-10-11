"""Pytest configuration and shared fixtures.

This module contains pytest configuration and fixtures that are shared
across all test modules.
"""

import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

# Add the project root to the Python path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def short_workspace() -> Iterator[Path]:
    """Provide an opt-in short temporary root for nested artifact/source fixtures.

    为什么要有它：非路径语义测试需要稳定到达被测行为；短根目录避免仓库和
    pytest 节点名耗尽 Windows 路径长度，显式选择保留专门长路径测试的原义。
    """
    temporary_root = Path(tempfile.gettempdir()).resolve()
    workspace = Path(tempfile.mkdtemp(prefix="rqa-", dir=temporary_root)).resolve()
    try:
        yield workspace
    finally:
        # 为什么要有它：只清理本次创建且未被重定向的目录，保护共享临时目录。
        if workspace.parent != temporary_root or workspace.resolve() != workspace:
            raise RuntimeError(f"Refusing cleanup of redirected test workspace: {workspace}")
        if workspace.exists():
            shutil.rmtree(workspace)


@pytest.fixture
def project_root() -> Path:
    """Return the project root directory path.

    Returns:
        Path to the project root directory.
    """
    return PROJECT_ROOT


@pytest.fixture
def sample_documents_dir(project_root: Path) -> Path:
    """Return the sample documents directory path.

    Args:
        project_root: The project root directory path.

    Returns:
        Path to the sample documents directory.
    """
    return project_root / "tests" / "fixtures" / "sample_documents"


@pytest.fixture
def config_dir(project_root: Path) -> Path:
    """Return the config directory path.

    Args:
        project_root: The project root directory path.

    Returns:
        Path to the config directory.
    """
    return project_root / "config"
