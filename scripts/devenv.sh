# Source this in every dev shell: keeps all caches/downloads on D:
export DND_ROOT="/d/dndmaster"
export DND_RUNTIME="$DND_ROOT/.runtime"
export PIP_CACHE_DIR="$(cygpath -w "$DND_RUNTIME/pip-cache")"
export HF_HOME="$(cygpath -w "$DND_RUNTIME/hf-cache")"
export OLLAMA_MODELS="$(cygpath -w "$DND_RUNTIME/models")"
export OLLAMA_HOST="127.0.0.1:11434"
export TMP="$(cygpath -w "$DND_RUNTIME/tmp")"
export TEMP="$TMP"
export PYTHONUTF8=1
export PATH="$DND_RUNTIME/venv/Scripts:$DND_RUNTIME/ollama:$PATH"
