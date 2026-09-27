from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AhmadConfig:
    root: Path
    data_dir: Path
    policy_dir: Path
    skills_dir: Path
    tools_dir: Path


def load_config() -> AhmadConfig:
    root = Path(__file__).resolve().parents[3]

    return AhmadConfig(
        root=root,
        data_dir=root / "data",
        policy_dir=root / "policies",
        skills_dir=root / "skills",
        tools_dir=root / "tools",
    )
