#!/usr/bin/env bash
#
# SPECTRA Periodic Intelligence Analysis — Devin GLM-5.2 Subagent
# =================================================================
#
# Spawned every 3 hours by the scheduler (or cron).
# Launches a Devin GLM-5.2 subagent to analyze intelligence data
# from QIHSE, then deletes the session when done.
#
# Usage:
#   ./scripts/periodic_intel_analysis.sh [DB_PATH]
#
# Default DB_PATH: ./spectra.db
#
# The script:
#   1. Exports current intelligence data from QIHSE/SQLite
#   2. Launches Devin GLM-5.2 in non-interactive mode with the analysis prompt
#   3. Saves the analysis output to data/intel_reports/
#   4. Deletes the Devin session
#

set -euo pipefail

DB_PATH="${1:-./spectra.db}"
REPORT_DIR="./data/intel_reports"
TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
REPORT_FILE="${REPORT_DIR}/intel_analysis_${TIMESTAMP}.md"
SESSION_LOG="/tmp/devin_intel_session_${TIMESTAMP}.log"

mkdir -p "${REPORT_DIR}"

echo "[INFO] SPECTRA Periodic Intelligence Analysis — $(date -u)"
echo "[INFO] DB: ${DB_PATH}"
echo "[INFO] Report: ${REPORT_FILE}"

# ─── Step 1: Export current intelligence data ────────────────────────────

echo "[INFO] Exporting intelligence data from QIHSE/SQLite..."

INTEL_EXPORT=$(python3 -c "
import json, sqlite3, sys
from pathlib import Path

db_path = '${DB_PATH}'
if not Path(db_path).exists():
    print(json.dumps({'error': f'Database not found: {db_path}'}))
    sys.exit(0)

# Check if it's a real SQLite file (not a Git-LFS pointer)
with open(db_path, 'rb') as f:
    header = f.read(16)
if header[:15] != b'SQLite format 3':
    print(json.dumps({'error': f'Not a SQLite database (Git-LFS pointer or corrupt): {db_path}'}))
    sys.exit(0)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

result = {'timestamp': '$(date -u +%Y-%m-%dT%H:%M:%SZ)', 'db': db_path}

# Evidence stats
try:
    rows = conn.execute('''
        SELECT evidence_type, direction, COUNT(*) as count,
               AVG(score) as avg_score, AVG(confidence) as avg_confidence
        FROM intelligence_evidence GROUP BY evidence_type, direction
        ORDER BY count DESC
    ''').fetchall()
    result['evidence_by_type'] = [dict(r) for r in rows]
    result['evidence_total'] = sum(r['count'] for r in rows)
except sqlite3.OperationalError:
    result['evidence_by_type'] = []
    result['evidence_total'] = 0

# Hypothesis stats
try:
    rows = conn.execute('''
        SELECT hypothesis_type, COUNT(*) as count,
               AVG(probability) as avg_probability,
               AVG(confidence) as avg_confidence,
               SUM(CASE WHEN probability > 0.7 THEN 1 ELSE 0 END) as high_confidence_count
        FROM intelligence_hypotheses GROUP BY hypothesis_type
        ORDER BY count DESC
    ''').fetchall()
    result['hypotheses_by_type'] = [dict(r) for r in rows]
    result['hypothesis_total'] = sum(r['count'] for r in rows)
except sqlite3.OperationalError:
    result['hypotheses_by_type'] = []
    result['hypothesis_total'] = 0

# Campaign stats
try:
    rows = conn.execute('''
        SELECT campaign_id, name, confidence, generated_at
        FROM intelligence_campaigns ORDER BY confidence DESC
    ''').fetchall()
    result['campaigns'] = [dict(r) for r in rows]
    result['campaign_total'] = len(rows)
except sqlite3.OperationalError:
    result['campaigns'] = []
    result['campaign_total'] = 0

# Top actors by evidence count
try:
    rows = conn.execute('''
        SELECT subject as entity, COUNT(*) as evidence_count,
               GROUP_CONCAT(DISTINCT evidence_type) as evidence_types
        FROM intelligence_evidence
        GROUP BY subject ORDER BY evidence_count DESC LIMIT 20
    ''').fetchall()
    result['top_entities_by_evidence'] = [dict(r) for r in rows]
except sqlite3.OperationalError:
    result['top_entities_by_evidence'] = []

# High-probability hypotheses (potential network links)
try:
    rows = conn.execute('''
        SELECT hypothesis_id, hypothesis_type, subject_a, subject_b,
               probability, confidence, generated_at
        FROM intelligence_hypotheses
        WHERE probability > 0.5
        ORDER BY probability DESC LIMIT 50
    ''').fetchall()
    result['high_probability_hypotheses'] = [dict(r) for r in rows]
except sqlite3.OperationalError:
    result['high_probability_hypotheses'] = []

# Recent evidence (last 100)
try:
    rows = conn.execute('''
        SELECT evidence_id, evidence_type, subject, object, score,
               confidence, direction, model, generated_at
        FROM intelligence_evidence
        ORDER BY generated_at DESC LIMIT 100
    ''').fetchall()
    result['recent_evidence'] = [dict(r) for r in rows]
except sqlite3.OperationalError:
    result['recent_evidence'] = []

# Graph edge summary
try:
    rows = conn.execute('''
        SELECT edge_type, COUNT(*) as count
        FROM index_graph_edges GROUP BY edge_type ORDER BY count DESC
    ''').fetchall()
    result['graph_edges_by_type'] = [dict(r) for r in rows]
except sqlite3.OperationalError:
    result['graph_edges_by_type'] = []

conn.close()
print(json.dumps(result, indent=2, default=str))
" 2>/dev/null) || INTEL_EXPORT='{"error": "export failed"}'

# Save the raw export
echo "${INTEL_EXPORT}" > "${REPORT_FILE%.md}.json"
echo "[INFO] Raw export: ${REPORT_FILE%.md}.json"

# Check if export succeeded — if not, skip the Devin subagent
EXPORT_ERROR=$(echo "${INTEL_EXPORT}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('error',''))" 2>/dev/null || echo "parse_error")
if [ -n "${EXPORT_ERROR}" ]; then
    echo "[WARN] Intelligence export failed: ${EXPORT_ERROR}"
    echo "[WARN] Skipping Devin subagent — no data to analyze."
    echo "Intelligence analysis skipped: ${EXPORT_ERROR}" > "${REPORT_FILE}"
    echo "[INFO] Report: ${REPORT_FILE}"
    echo "[INFO] Done (no data)."
    exit 0
fi

# Check if there's actual intelligence data
EVIDENCE_TOTAL=$(echo "${INTEL_EXPORT}" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('evidence_total',0))" 2>/dev/null || echo 0)
if [ "${EVIDENCE_TOTAL}" -eq 0 ] 2>/dev/null; then
    echo "[WARN] No intelligence evidence found in database (evidence_total=0)"
    echo "[WARN] Skipping Devin subagent — nothing to analyze."
    echo "No intelligence evidence found in the database. Nothing to analyze." > "${REPORT_FILE}"
    echo "[INFO] Report: ${REPORT_FILE}"
    echo "[INFO] Done (no evidence)."
    exit 0
fi

echo "[INFO] Evidence count: ${EVIDENCE_TOTAL} — proceeding with analysis."

# ─── Step 1b: Run SPECTRA CLI intelligence commands for richer data ───────

echo "[INFO] Running SPECTRA CLI intelligence commands..."

CLI_OUTPUT=""

# Run pattern detection (recurring + cross-actor)
CLI_OUTPUT="${CLI_OUTPUT}\n\n=== PATTERNS (recurring) ===\n"
CLI_OUTPUT="${CLI_OUTPUT}$(python3 -m tgarchive intel patterns --mode recurring --db ${DB_PATH} --json 2>/dev/null || echo 'patterns command failed')\n"

CLI_OUTPUT="${CLI_OUTPUT}\n\n=== PATTERNS (cross-actor) ===\n"
CLI_OUTPUT="${CLI_OUTPUT}$(python3 -m tgarchive intel patterns --mode cross-actor --db ${DB_PATH} --json 2>/dev/null || echo 'cross-actor patterns failed')\n"

# Get top entities by evidence count and run conclusions on each
TOP_ENTITIES=$(echo "${INTEL_EXPORT}" | python3 -c "
import sys, json
d = json.load(sys.stdin)
entities = d.get('top_entities_by_evidence', [])
for e in entities[:5]:
    # Extract user ID from canonical entity ID like 'telegram:user:123'
    eid = e.get('entity', '')
    parts = eid.split(':')
    if len(parts) >= 3 and parts[-2] == 'user':
        print(parts[-1])
" 2>/dev/null)

if [ -n "${TOP_ENTITIES}" ]; then
    CLI_OUTPUT="${CLI_OUTPUT}\n\n=== CONCLUSIONS (top entities) ===\n"
    for UID in ${TOP_ENTITIES}; do
        CLI_OUTPUT="${CLI_OUTPUT}\n--- Entity: user:${UID} ---\n"
        CLI_OUTPUT="${CLI_OUTPUT}$(python3 -m tgarchive intel conclude ${UID} --type user --db ${DB_PATH} --json 2>/dev/null || echo "conclude failed for ${UID}")\n"
    done
fi

# Cross-index top entities
if [ -n "${TOP_ENTITIES}" ]; then
    CLI_OUTPUT="${CLI_OUTPUT}\n\n=== CROSS-INDEX (top entities) ===\n"
    for UID in ${TOP_ENTITIES}; do
        CLI_OUTPUT="${CLI_OUTPUT}\n--- Entity: user:${UID} ---\n"
        CLI_OUTPUT="${CLI_OUTPUT}$(python3 -m tgarchive intel cross-index ${UID} --type user --db ${DB_PATH} --json 2>/dev/null || echo "cross-index failed for ${UID}")\n"
    done
fi

echo "[INFO] CLI output collected: $(echo "${CLI_OUTPUT}" | wc -c) bytes"

# ─── Step 2: Build the analysis prompt ────────────────────────────────────

PROMPT_FILE="/tmp/devin_intel_prompt_${TIMESTAMP}.md"
cat > "${PROMPT_FILE}" << 'PROMPT_HEADER'
You are a SPECTRA intelligence analyst. Analyze the following intelligence data
exported from QIHSE (the native multi-model database) and produce a structured
analysis report.

Your analysis should cover:

1. **Threat Assessment Summary** — Overall threat landscape based on evidence
   types, scores, and confidence levels. What are the most significant threats?

2. **Network Analysis** — Based on the high-probability hypotheses, what actor
   networks are visible? Which actors appear to be linked? What do the
   hypothesis types tell us about the nature of these links?

3. **Campaign Assessment** — What campaigns have been identified? What is the
   confidence level? Which actors are involved?

4. **Pattern Detection** — Are there recurring evidence patterns across actors?
   Which evidence types appear most frequently? Are there clusters of similar
   evidence that might indicate coordinated behavior?

5. **Key Findings** — The top 5 most significant findings from this analysis
   cycle, ranked by importance.

6. **Recommended Actions** — What should the analyst do next? Which actors
   need further investigation? Which hypotheses need analyst confirmation
   or rejection?

7. **Data Quality Assessment** — Is there sufficient evidence? Are there
   gaps? What additional collection is needed?

Format the report in Markdown with clear section headers.

--- INTELLIGENCE DATA EXPORT ---
PROMPT_HEADER

echo "${INTEL_EXPORT}" >> "${PROMPT_FILE}"
echo "" >> "${PROMPT_FILE}"
echo "--- SPECTRA CLI ANALYSIS OUTPUT (patterns, conclusions, cross-index) ---" >> "${PROMPT_FILE}"
echo -e "${CLI_OUTPUT}" >> "${PROMPT_FILE}"
echo "--- END CLI OUTPUT ---" >> "${PROMPT_FILE}"
echo "" >> "${PROMPT_FILE}"
echo "--- END DATA ---" >> "${PROMPT_FILE}"

echo "[INFO] Prompt file: ${PROMPT_FILE}"
echo "[INFO] Prompt size: $(wc -c < ${PROMPT_FILE}) bytes"

# ─── Step 3: Launch Devin GLM-5.2 subagent ────────────────────────────────

echo "[INFO] Launching Devin GLM-5.2 subagent..."

# Run Devin in non-interactive mode with GLM-5.2
# --respect-workspace-trust false: skip trust prompt (non-interactive)
# --permission-mode dangerous: auto-approve all tools (unattended run)
# --model glm-5-2: use GLM-5.2 High (free, 200K context)
# Note: Devin doesn't have --ephemeral, so we delete the session after.
# We capture the session list before and after to find the new session.
SESSIONS_BEFORE=$(devin list 2>/dev/null | grep -oP '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}' || true)

devin --model glm-5-2 \
      --print \
      --respect-workspace-trust false \
      --permission-mode dangerous \
      --prompt-file "${PROMPT_FILE}" \
      > "${SESSION_LOG}" 2>&1 &

DEVIN_PID=$!
echo "[INFO] Devin PID: ${DEVIN_PID}"
echo "[INFO] Session log: ${SESSION_LOG}"

# Wait for completion (max 30 minutes)
TIMEOUT=1800
ELAPSED=0
while kill -0 ${DEVIN_PID} 2>/dev/null; do
    sleep 10
    ELAPSED=$((ELAPSED + 10))
    if [ ${ELAPSED} -ge ${TIMEOUT} ]; then
        echo "[WARN] Devin timed out after ${TIMEOUT}s, killing..."
        kill ${DEVIN_PID} 2>/dev/null || true
        break
    fi
done

# Wait for the process to fully exit
wait ${DEVIN_PID} 2>/dev/null || true
EXIT_CODE=$?

echo "[INFO] Devin exited with code: ${EXIT_CODE}"

# ─── Step 4: Extract analysis from session log ───────────────────────────

# The session log contains the full Devin output. Extract the analysis.
# Devin prints the response to stdout, which we captured in SESSION_LOG.
if [ -s "${SESSION_LOG}" ]; then
    # Try to extract just the model response (skip control chars/warnings)
    # The actual analysis content comes after any setup output
    python3 -c "
import sys
lines = open('${SESSION_LOG}', 'r', errors='replace').readlines()
# Filter out ANSI escape sequences and control characters
import re
clean = []
for line in lines:
    # Remove ANSI escape codes
    line = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', line)
    line = re.sub(r'\x1b\][^\x07]*\x07', '', line)
    line = re.sub(r'\[\?2004[hl]', '', line)
    clean.append(line)
content = ''.join(clean)
# Write the cleaned output
with open('${REPORT_FILE}', 'w') as f:
    f.write(content)
print(f'Analysis written to ${REPORT_FILE}')
" 2>/dev/null || cp "${SESSION_LOG}" "${REPORT_FILE}"

    echo "[INFO] Analysis report: ${REPORT_FILE}"
    echo "[INFO] Report size: $(wc -c < ${REPORT_FILE}) bytes"
else
    echo "[WARN] No output from Devin session"
    echo "No analysis output produced." > "${REPORT_FILE}"
fi

# ─── Step 5: Delete the Devin session ─────────────────────────────────────

echo "[INFO] Cleaning up Devin session..."

# Find the new session by diffing before/after session lists
SESSIONS_AFTER=$(devin list 2>/dev/null | grep -oP '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}' || true)

# Find session IDs that are in AFTER but not in BEFORE
NEW_SESSION=$(comm -13 <(echo "${SESSIONS_BEFORE}" | sort) <(echo "${SESSIONS_AFTER}" | sort) | head -1)

if [ -n "${NEW_SESSION}" ]; then
    echo "[INFO] Deleting session: ${NEW_SESSION}"
    devin rm "${NEW_SESSION}" --force 2>/dev/null && echo "[INFO] Session deleted" || echo "[WARN] Failed to delete session"
else
    echo "[WARN] Could not find new session ID to delete (may have already been cleaned up)"
fi

# Clean up temp files
rm -f "${PROMPT_FILE}" 2>/dev/null || true

echo "[INFO] Periodic intelligence analysis complete."
echo "[INFO] Report: ${REPORT_FILE}"
echo "[INFO] Raw data: ${REPORT_FILE%.md}.json"
echo "[INFO] Session log: ${SESSION_LOG}"
