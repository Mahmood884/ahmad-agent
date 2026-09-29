"""Local React/Tailwind project generation and governed shadcn component installs."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ahmad.execution.mock_tool import ToolResult


THEMES = {
    "ocean": {
        "background": "#ffffff",
        "foreground": "#172033",
        "primary": "#1d4ed8",
        "primary_foreground": "#ffffff",
        "muted": "#f1f5f9",
        "muted_foreground": "#334155",
    },
    "forest": {
        "background": "#ffffff",
        "foreground": "#17251c",
        "primary": "#166534",
        "primary_foreground": "#ffffff",
        "muted": "#f0fdf4",
        "muted_foreground": "#14532d",
    },
    "berry": {
        "background": "#ffffff",
        "foreground": "#2b1422",
        "primary": "#9d174d",
        "primary_foreground": "#ffffff",
        "muted": "#fdf2f8",
        "muted_foreground": "#701a3c",
    },
}

SHADCN_COMPONENTS = frozenset(
    {
        "accordion", "alert", "alert-dialog", "aspect-ratio", "avatar",
        "badge", "breadcrumb", "button", "calendar", "card", "checkbox",
        "collapsible", "command", "context-menu", "dialog", "drawer",
        "dropdown-menu", "form", "hover-card", "input", "label", "menubar",
        "navigation-menu", "popover", "progress", "radio-group", "scroll-area",
        "select", "separator", "sheet", "skeleton", "slider", "sonner",
        "switch", "table", "tabs", "textarea", "toast", "toggle",
        "toggle-group", "tooltip",
    }
)


def _parse_json_action(action: str, name: str) -> dict:
    prefix = f"{name}:"
    if not action.startswith(prefix):
        raise ValueError(f"Action must start with '{prefix}'")
    try:
        payload = json.loads(action[len(prefix):])
    except json.JSONDecodeError as exc:
        raise ValueError(f"Action payload must be valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Action payload must be a JSON object")
    return payload


def _safe_target(root: Path, directory: str, *, name: str | None = None) -> Path:
    target = Path(directory).expanduser().resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Project directory must be under {root}") from exc
    if target == root:
        raise ValueError("Project directory cannot be the workspace root")
    if name is not None and target.name != name:
        raise ValueError("Project directory basename must match the project name")
    return target


def _hex_rgb(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError(f"Invalid six-digit hex color: {value}")
    return tuple(int(value[index:index + 2], 16) for index in (1, 3, 5))


def _luminance(value: str) -> float:
    channels = [channel / 255 for channel in _hex_rgb(value)]
    linear = [
        item / 12.92 if item <= 0.04045 else ((item + 0.055) / 1.055) ** 2.4
        for item in channels
    ]
    return sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def _contrast(first: str, second: str) -> float:
    luminances = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (luminances[0] + 0.05) / (luminances[1] + 0.05)


class ThemePickerTool:
    name = "theme_picker"
    version = "1.0"

    def run(self, action: str) -> ToolResult:
        try:
            payload = _parse_json_action(action, self.name)
            theme_name = payload.get("name")
            if not isinstance(theme_name, str) or theme_name not in THEMES:
                return ToolResult(
                    False, self.name,
                    f"ERROR: Unknown theme. Choose one of: {', '.join(sorted(THEMES))}",
                    None,
                )
            theme = THEMES[theme_name]
            ratios = {
                "text_on_background": round(
                    _contrast(theme["foreground"], theme["background"]), 2
                ),
                "primary_text_on_primary": round(
                    _contrast(theme["primary_foreground"], theme["primary"]), 2
                ),
                "muted_text_on_muted": round(
                    _contrast(theme["muted_foreground"], theme["muted"]), 2
                ),
            }
            if min(ratios.values()) < 4.5:
                return ToolResult(False, self.name, "ERROR: Theme fails WCAG AA contrast.", None)
            return ToolResult(
                True, self.name,
                json.dumps(
                    {"name": theme_name, "colors": theme, "contrast_ratios": ratios},
                    indent=2,
                ),
                None,
            )
        except ValueError as exc:
            return ToolResult(False, self.name, f"ERROR: {exc}", None)


class GenerateUITool:
    name = "generate_ui"
    version = "1.0"

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root).expanduser().resolve() if root else Path.cwd().resolve()

    def run(self, action: str) -> ToolResult:
        temp_dir: Path | None = None
        try:
            payload = _parse_json_action(action, self.name)
            project_name = payload.get("name")
            description = payload.get("description")
            theme_name = payload.get("theme", "ocean")
            if not isinstance(project_name, str) or not re.fullmatch(
                r"[a-z][a-z0-9-]{1,48}", project_name
            ):
                raise ValueError("name must be a lowercase project slug (2-49 characters)")
            if not isinstance(description, str) or not description.strip():
                raise ValueError("description is required")
            if len(description) > 1000:
                raise ValueError("description must not exceed 1000 characters")
            if not isinstance(theme_name, str) or theme_name not in THEMES:
                raise ValueError(f"theme must be one of: {', '.join(sorted(THEMES))}")

            target = _safe_target(self.root, str(self.root / project_name), name=project_name)
            if target.exists():
                raise ValueError(f"Project directory already exists: {target}")
            self.root.mkdir(parents=True, exist_ok=True)
            temp_dir = Path(tempfile.mkdtemp(prefix=f".{project_name}-", dir=self.root))
            theme = THEMES[theme_name]
            quoted_name = json.dumps(project_name.replace("-", " ").title())
            quoted_description = json.dumps(description.strip())
            theme_css = "\n".join(
                f"  --{key.replace('_', '-')}: {value};" for key, value in theme.items()
            )

            files = {
                ".ahmad-ui-project": "react-tailwind-shadcn-v1\n",
                "package.json": json.dumps(
                    {
                        "name": project_name,
                        "private": True,
                        "version": "0.1.0",
                        "type": "module",
                        "scripts": {
                            "dev": "vite",
                            "build": "tsc -b && vite build",
                            "preview": "vite preview",
                        },
                        "dependencies": {
                            "clsx": "^2.1.1",
                            "react": "^19.0.0",
                            "react-dom": "^19.0.0",
                            "tailwind-merge": "^3.0.0",
                        },
                        "devDependencies": {
                            "@tailwindcss/vite": "^4.0.0",
                            "@types/react": "^19.0.0",
                            "@types/react-dom": "^19.0.0",
                            "@vitejs/plugin-react": "^4.3.4",
                            "tailwindcss": "^4.0.0",
                            "typescript": "~5.7.2",
                            "vite": "^6.0.0",
                        },
                    },
                    indent=2,
                ) + "\n",
                "index.html": (
                    "<!doctype html>\n<html lang=\"en\">\n<head>\n"
                    "  <meta charset=\"UTF-8\" />\n"
                    "  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />\n"
                    f"  <title>{project_name.replace('&', '&amp;').replace('<', '&lt;')}</title>\n"
                    "</head>\n<body>\n  <div id=\"root\"></div>\n"
                    "  <script type=\"module\" src=\"/src/main.tsx\"></script>\n"
                    "</body>\n</html>\n"
                ),
                "vite.config.ts": (
                    'import { defineConfig } from "vite";\n'
                    'import react from "@vitejs/plugin-react";\n'
                    'import tailwindcss from "@tailwindcss/vite";\n'
                    'import path from "node:path";\n'
                    'import { fileURLToPath } from "node:url";\n\n'
                    'const dirname = path.dirname(fileURLToPath(import.meta.url));\n\n'
                    'export default defineConfig({\n'
                    '  plugins: [react(), tailwindcss()],\n'
                    '  resolve: { alias: { "@": path.resolve(dirname, "src") } },\n'
                    '});\n'
                ),
                "tsconfig.json": (
                    '{\n  "files": [],\n  "references": [\n'
                    '    { "path": "./tsconfig.app.json" }\n  ]\n}\n'
                ),
                "tsconfig.app.json": (
                    '{\n  "compilerOptions": {\n    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.app.tsbuildinfo",\n'
                    '    "target": "ES2022",\n    "useDefineForClassFields": true,\n'
                    '    "lib": ["ES2022", "DOM", "DOM.Iterable"],\n    "module": "ESNext",\n'
                    '    "skipLibCheck": true,\n    "moduleResolution": "bundler",\n'
                    '    "allowImportingTsExtensions": true,\n    "verbatimModuleSyntax": true,\n'
                    '    "moduleDetection": "force",\n    "noEmit": true,\n'
                    '    "jsx": "react-jsx",\n    "strict": true,\n    "baseUrl": ".",\n'
                    '    "paths": { "@/*": ["./src/*"] }\n  },\n'
                    '  "include": ["src"]\n}\n'
                ),
                "tsconfig.node.json": (
                    '{\n  "compilerOptions": {\n'
                    '    "tsBuildInfoFile": "./node_modules/.tmp/tsconfig.node.tsbuildinfo",\n'
                    '    "target": "ES2023",\n    "lib": ["ES2023"],\n'
                    '    "module": "ESNext",\n    "skipLibCheck": true,\n'
                    '    "moduleResolution": "bundler",\n    "allowImportingTsExtensions": true,\n'
                    '    "verbatimModuleSyntax": true,\n    "moduleDetection": "force",\n'
                    '    "noEmit": true,\n    "strict": true\n  },\n'
                    '  "include": ["vite.config.ts"]\n}\n'
                ),
                "components.json": json.dumps(
                    {
                        "$schema": "https://ui.shadcn.com/schema.json",
                        "style": "new-york",
                        "rsc": False,
                        "tsx": True,
                        "tailwind": {
                            "config": "",
                            "css": "src/index.css",
                            "baseColor": "neutral",
                            "cssVariables": True,
                            "prefix": "",
                        },
                        "aliases": {
                            "components": "@/components",
                            "utils": "@/lib/utils",
                            "ui": "@/components/ui",
                            "lib": "@/lib",
                            "hooks": "@/hooks",
                        },
                        "iconLibrary": "lucide",
                    },
                    indent=2,
                ) + "\n",
                "src/main.tsx": (
                    'import React from "react";\n'
                    'import ReactDOM from "react-dom/client";\n'
                    'import App from "./App";\n'
                    'import "./index.css";\n\n'
                    'ReactDOM.createRoot(document.getElementById("root")!).render(\n'
                    '  <React.StrictMode><App /></React.StrictMode>,\n'
                    ');\n'
                ),
                "src/App.tsx": (
                    'function App() {\n'
                    '  return (\n'
                    '    <main className="mx-auto flex min-h-screen max-w-4xl items-center px-6 py-16">\n'
                    '      <section className="w-full rounded-xl border bg-card p-8 text-card-foreground shadow-sm">\n'
                    f'        <p className="mb-3 text-sm font-medium text-primary">{{{quoted_name}}}</p>\n'
                    f'        <h1 className="text-3xl font-semibold tracking-tight">{{{quoted_description}}}</h1>\n'
                    '        <p className="mt-4 text-muted-foreground">A React, Tailwind CSS, and shadcn/ui-ready interface.</p>\n'
                    '        <button type="button" className="mt-8 rounded-md bg-primary px-4 py-2 font-medium text-primary-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary">\n'
                    '          Get started\n'
                    '        </button>\n'
                    '      </section>\n'
                    '    </main>\n'
                    '  );\n'
                    '}\n\n'
                    'export default App;\n'
                ),
                "src/index.css": (
                    '@import "tailwindcss";\n\n'
                    '@theme inline {\n'
                    '  --color-background: var(--background);\n'
                    '  --color-foreground: var(--foreground);\n'
                    '  --color-primary: var(--primary);\n'
                    '  --color-primary-foreground: var(--primary-foreground);\n'
                    '  --color-muted: var(--muted);\n'
                    '  --color-muted-foreground: var(--muted-foreground);\n'
                    '  --color-card: var(--background);\n'
                    '  --color-card-foreground: var(--foreground);\n'
                    '}\n\n'
                    ':root {\n'
                    f'{theme_css}\n'
                    '  color-scheme: light;\n'
                    '  font-family: ui-sans-serif, system-ui, sans-serif;\n'
                    '  font-synthesis: none;\n'
                    '  text-rendering: optimizeLegibility;\n'
                    '  background: var(--background);\n'
                    '  color: var(--foreground);\n'
                    '}\n\n'
                    'body { margin: 0; min-width: 320px; min-height: 100vh; }\n'
                    'button { cursor: pointer; }\n'
                    '* { box-sizing: border-box; }\n'
                ),
                "src/lib/utils.ts": (
                    'import { clsx, type ClassValue } from "clsx";\n'
                    'import { twMerge } from "tailwind-merge";\n\n'
                    'export function cn(...inputs: ClassValue[]) {\n'
                    '  return twMerge(clsx(inputs));\n'
                    '}\n'
                ),
                "README.md": (
                    f"# {project_name}\n\n{description.strip()}\n\n"
                    "## Getting started\n\n"
                    "```sh\nnpm install\nnpm run dev\n```\n\n"
                    "Add shadcn/ui components through ahmad-agent's `component_lib` tool.\n"
                ),
            }
            for relative, contents in files.items():
                destination = temp_dir / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(contents, encoding="utf-8")
            os.replace(temp_dir, target)
            temp_dir = None
            return ToolResult(
                True, self.name,
                f"SUCCESS: Created React/Tailwind project at {target} using theme '{theme_name}'. "
                "Run npm install, then npm run dev.",
                None,
            )
        except (OSError, ValueError) as exc:
            return ToolResult(False, self.name, f"ERROR: {type(exc).__name__}: {exc}", None)
        finally:
            if temp_dir is not None:
                shutil.rmtree(temp_dir, ignore_errors=True)


class ComponentLibraryTool:
    name = "component_lib"
    version = "1.0"
    TIMEOUT_SECONDS = 180

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root).expanduser().resolve() if root else Path.cwd().resolve()

    def run(self, action: str) -> ToolResult:
        try:
            payload = _parse_json_action(action, self.name)
            if payload.get("allow_network") is not True:
                raise ValueError(
                    "set allow_network=true only after explicitly approving the component download"
                )
            project_dir = payload.get("project_dir")
            component = payload.get("component")
            if not isinstance(project_dir, str) or not project_dir.strip():
                raise ValueError("project_dir is required")
            if not isinstance(component, str) or component not in SHADCN_COMPONENTS:
                return ToolResult(
                    False, self.name,
                    f"ERROR: Unsupported component. Choose one of: {', '.join(sorted(SHADCN_COMPONENTS))}",
                    None,
                )
            target = _safe_target(self.root, project_dir)
            if not (target / ".ahmad-ui-project").is_file():
                raise ValueError("Only projects generated by generate_ui can be modified")
            if not (target / "components.json").is_file() or not (target / "package.json").is_file():
                raise ValueError("Project is missing its shadcn or package configuration")
            component_file = target / "src" / "components" / "ui" / f"{component}.tsx"
            if component_file.exists():
                raise ValueError(f"Component already exists: {component_file}")
            if shutil.which("npx") is None:
                raise ValueError("npx is required to run the official shadcn CLI")
            result = subprocess.run(
                ["npx", "--yes", "shadcn@latest", "add", "--yes", component],
                cwd=target,
                capture_output=True,
                text=True,
                timeout=self.TIMEOUT_SECONDS,
                check=False,
            )
            output = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
            if result.returncode != 0:
                return ToolResult(
                    False, self.name,
                    f"INSTALL_FAILED (exit {result.returncode}): {output}",
                    None,
                )
            return ToolResult(
                True, self.name,
                f"SUCCESS: Added shadcn/ui '{component}' to {target}\n{output}".rstrip(),
                None,
            )
        except subprocess.TimeoutExpired:
            return ToolResult(
                False, self.name,
                f"ERROR: shadcn CLI timed out after {self.TIMEOUT_SECONDS} seconds",
                None,
            )
        except (OSError, ValueError) as exc:
            return ToolResult(False, self.name, f"ERROR: {type(exc).__name__}: {exc}", None)
