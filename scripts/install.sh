#!/usr/bin/env bash
# Install the CodeAtlas skill for one or more coding agents.
set -eo pipefail

usage() {
  cat <<'EOF'
Usage: install.sh [--force] [--link] [--target DIR]... [--canonical DIR]

  --force            replace an existing code-atlas installation
  --link             keep one canonical copy in ~/.agents/skills/code-atlas
                     and symlink the other targets to it
  --target DIR       parent skill directory (repeatable); default: OpenCode,
                     Claude Code, Codex, Cursor, and ~/.agents
  --canonical DIR    canonical install path used by --link

Examples:
  ./install.sh --force
  ./install.sh --target ~/.claude/skills --force
  ./install.sh --link --force
EOF
}

FORCE=0
LINK=0
CANONICAL="${HOME}/.agents/skills/code-atlas"
TARGETS=()

while [ $# -gt 0 ]; do
  case "$1" in
    --force|-f) FORCE=1 ;;
    --link|-l) LINK=1 ;;
    --target|-t)
      [ $# -ge 2 ] || { echo "error: --target needs a directory" >&2; exit 2; }
      TARGETS+=("$2"); shift ;;
    --canonical)
      [ $# -ge 2 ] || { echo "error: --canonical needs a directory" >&2; exit 2; }
      CANONICAL="$2"; shift ;;
    --help|-h) usage; exit 0 ;;
    *) echo "error: unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILL_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

if [ ! -f "${SKILL_ROOT}/SKILL.md" ]; then
  echo "error: SKILL.md not found in ${SKILL_ROOT}" >&2
  exit 1
fi

if [ ${#TARGETS[@]} -eq 0 ]; then
  TARGETS=(
    "${HOME}/.config/opencode/skills"
    "${HOME}/.claude/skills"
    "${HOME}/.codex/skills"
    "${HOME}/.cursor/skills"
    "${HOME}/.agents/skills"
  )
fi

PYTHON_BIN="$(command -v python3 || command -v python || true)"
PY_VERSION="not found"
if [ -n "${PYTHON_BIN}" ]; then
  PY_VERSION="$("${PYTHON_BIN}" --version 2>&1)"
fi

expand_path() {
  case "$1" in
    "~") printf '%s\n' "${HOME}" ;;
    "~/"*) printf '%s\n' "${HOME}/${1#\~/}" ;;
    *) printf '%s\n' "$1" ;;
  esac
}

same_path() {
  [ "$(cd "$1" 2>/dev/null && pwd -P || printf '%s' "$1")" = "$(cd "$2" 2>/dev/null && pwd -P || printf '%s' "$2")" ]
}

install_payload() {
  local dest="$1"
  if [ -e "${dest}" ] || [ -L "${dest}" ]; then
    if [ "${FORCE}" -ne 1 ]; then
      echo "  skip  ${dest} (exists; use --force to replace)"
      return 1
    fi
    rm -rf "${dest}"
  fi
  mkdir -p "${dest}"
  for item in SKILL.md README.md LICENSE scripts references assets; do
    if [ -e "${SKILL_ROOT}/${item}" ]; then
      cp -R "${SKILL_ROOT}/${item}" "${dest}/"
    fi
  done
  find "${dest}" -type d \( -name __pycache__ -o -name .code-atlas \) -prune -exec rm -rf {} + 2>/dev/null || true
  if [ ! -f "${dest}/scripts/atlas.py" ]; then
    echo "error: install incomplete: ${dest}/scripts/atlas.py missing" >&2
    exit 1
  fi
  echo "  copy  ${dest}"
}

install_link() {
  local dest="$1" target="$2"
  if same_path "${dest}" "${target}"; then return 0; fi
  if [ -e "${dest}" ] || [ -L "${dest}" ]; then
    if [ "${FORCE}" -ne 1 ]; then
      echo "  skip  ${dest} (exists; use --force to replace)"
      return 0
    fi
    rm -rf "${dest}"
  fi
  mkdir -p "$(dirname "${dest}")"
  ln -s "${target}" "${dest}"
  echo "  link  ${dest} -> ${target}"
}

echo "CodeAtlas installer"
echo "  source: ${SKILL_ROOT}"
echo "  python: ${PY_VERSION}"
echo ""

if [ "${LINK}" -eq 1 ]; then
  if same_path "${SKILL_ROOT}" "${CANONICAL}"; then
    echo "  keep  ${CANONICAL} (already the source)"
  else
    install_payload "${CANONICAL}" || true
  fi
  if [ ! -f "${CANONICAL}/scripts/atlas.py" ]; then
    echo "error: canonical install missing: ${CANONICAL}/scripts/atlas.py" >&2
    exit 1
  fi
  for parent in "${TARGETS[@]}"; do
    parent="$(expand_path "${parent}")"
    install_link "${parent}/code-atlas" "${CANONICAL}"
  done
else
  for parent in "${TARGETS[@]}"; do
    parent="$(expand_path "${parent}")"
    dest="${parent}/code-atlas"
    if same_path "${SKILL_ROOT}" "${dest}"; then
      echo "  keep  ${dest} (already the source)"
      continue
    fi
    install_payload "${dest}" || true
  done
fi

echo ""
echo "Done. Restart your agent (or reload the window) to pick up the skill."
echo "Verify with: ${PYTHON_BIN:-python3} <skills-dir>/code-atlas/scripts/atlas.py --version"
