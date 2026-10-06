from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_WORKSPACE_DIRNAME = "ahmad-workspace"


@dataclass(frozen=True)
class AhmadConfig:
    root: Path
    data_dir: Path
    policy_dir: Path
    skills_dir: Path
    tools_dir: Path
    # Agent output workspace, deliberately outside the repository.
    workspace_dir: Path = field(
        default_factory=lambda: Path.home() / DEFAULT_WORKSPACE_DIRNAME
    )


def load_config() -> AhmadConfig:
    root = Path(__file__).resolve().parents[3]

    return AhmadConfig(
        root=root,
        data_dir=root / "data",
        policy_dir=root / "policies",
        skills_dir=root / "skills",
        tools_dir=root / "tools",
        workspace_dir=Path.home() / DEFAULT_WORKSPACE_DIRNAME,
    )
