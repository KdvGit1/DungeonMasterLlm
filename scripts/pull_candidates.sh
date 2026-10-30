#!/usr/bin/env bash
# Pull benchmark candidate models into D:\dndmaster\.runtime\models
source /d/dndmaster/scripts/devenv.sh
MODELS=(
  "huihui_ai/gemma-4-abliterated:12b"
  "huihui_ai/qwen3.5-abliterated:9b"
  "hf.co/igorls/gemma-4-12B-it-heretic-GGUF:Q4_K_M"
  "hf.co/bartowski/TheDrummer_Rocinante-X-12B-v1-GGUF:Q4_K_M"
  "hf.co/SicariusSicariiStuff/Impish_Bloodmoon_12B_GGUF:Q4_K_M"
  "huihui_ai/gemma-4-abliterated:26b"
)
for m in "${MODELS[@]}"; do
  echo "=== $(date +%H:%M:%S) pulling $m"
  ollama pull "$m" 2>&1 | tr '\r' '\n' | grep -v "pulling [0-9a-f]\{12\}.*[0-9]%" | tail -2
  echo "=== $(date +%H:%M:%S) done $m (exit ${PIPESTATUS[0]})"
done
ollama list
