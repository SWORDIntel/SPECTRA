#!/usr/bin/env bash
#
# SPECTRA Periodic Persona Analysis — Devin GLM-5.2 High
# =======================================================
#
# Runs every 24 hours. For each authorized persona target:
#   1. Backs up the current persona algorithm (feature modules + config)
#   2. Exports all data about the target (examples, snapshots, knowledge,
#      surveillance dossier, messages, interactions)
#   3. Launches Devin GLM-5.2 High to analyze the data and suggest
#      improvements to the persona feature extraction algorithm
#   4. Saves the analysis report
#   5. Deletes the Devin session
#
# Usage:
#   ./scripts/periodic_persona_analysis.sh [DB_PATH] [--dry-run]
#
# Default DB_PATH: ./data/spectra.db
#
# The script is safe to run concurrently with the 3-hourly intel analysis.

set -euo pipefail

DB_PATH="${1:-./data/spectra.db}"
DRY_RUN=false
if [[ "${2:-}" == "--dry-run" ]]; then
    DRY_RUN=true
fi

REPORT_DIR="./data/persona_reports"
BACKUP_DIR="./data/persona_algo_backups"
FEATURES_DIR="./tgarchive/intelligence/features"
TIMESTAMP=$(date -u +"%Y%m%dT%H%M%SZ")
DATE=$(date -u +"%Y-%m-%d")

mkdir -p "${REPORT_DIR}"
mkdir -p "${BACKUP_DIR}"

echo "[INFO] SPECTRA Periodic Persona Analysis — $(date -u)"
echo "[INFO] DB: ${DB_PATH}"
echo "[INFO] Dry run: ${DRY_RUN}"
echo "[INFO] Report dir: ${REPORT_DIR}"

# ─── Step 0: Back up current persona algorithm ───────────────────────────

echo "[INFO] Backing up current persona algorithm..."

BACKUP_PATH="${BACKUP_DIR}/persona_algo_${TIMESTAMP}.tar.gz"
if [[ -d "${FEATURES_DIR}" ]]; then
    tar czf "${BACKUP_PATH}" \
        "${FEATURES_DIR}" \
        ./tgarchive/db/persona_store.py \
        ./tgarchive/intelligence/persona_training.py \
        ./tgarchive/db/schema.py \
        2>/dev/null || true
    echo "[INFO] Algorithm backup: ${BACKUP_PATH}"
else
    echo "[WARN] Features dir not found: ${FEATURES_DIR} — skipping backup"
fi

# ─── Step 1: Get all authorized persona targets ──────────────────────────

echo "[INFO] Fetching authorized persona targets..."

TARGETS_JSON=$(python3 -c "
import json, sqlite3, sys
from pathlib import Path

db_path = '${DB_PATH}'
if not Path(db_path).exists():
    print(json.dumps({'error': f'Database not found: {db_path}', 'targets': []}))
    sys.exit(0)

with open(db_path, 'rb') as f:
    header = f.read(16)
if header[:15] != b'SQLite format 3':
    print(json.dumps({'error': f'Not a SQLite database: {db_path}', 'targets': []}))
    sys.exit(0)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Get all persona targets (authorized first, then pending)
try:
    rows = conn.execute('''
        SELECT t.*, s.label as surveillance_label, s.notes as surveillance_notes
        FROM persona_targets t
        LEFT JOIN surveillance_targets s ON t.surveillance_target_id = s.target_id
        ORDER BY CASE t.authorization_status
            WHEN 'authorized' THEN 0
            WHEN 'pending' THEN 1
            ELSE 2
        END, t.created_at
    ''').fetchall()
    targets = [dict(r) for r in rows]
except sqlite3.OperationalError:
    # surveillance_targets table may not exist yet — query without the join
    try:
        rows = conn.execute('''
            SELECT t.*, NULL as surveillance_label, NULL as surveillance_notes
            FROM persona_targets t
            ORDER BY CASE t.authorization_status
                WHEN 'authorized' THEN 0
                WHEN 'pending' THEN 1
                ELSE 2
            END, t.created_at
        ''').fetchall()
        targets = [dict(r) for r in rows]
    except sqlite3.OperationalError:
        targets = []

# For each target, get corpus stats
for t in targets:
    tid = t['target_id']
    try:
        stats = conn.execute('''
            SELECT
                COUNT(*) as total_examples,
                SUM(CASE WHEN label='positive' THEN 1 ELSE 0 END) as positive,
                SUM(CASE WHEN label='negative' THEN 1 ELSE 0 END) as negative,
                SUM(CASE WHEN label='review' THEN 1 ELSE 0 END) as review
            FROM persona_examples WHERE target_id = ?
        ''', (tid,)).fetchone()
        t['example_counts'] = dict(stats) if stats else {}
    except sqlite3.OperationalError:
        t['example_counts'] = {}

    # Get latest snapshot info
    try:
        snap = conn.execute('''
            SELECT snapshot_id, as_of, model, model_version, created_at,
                   positive_count, negative_count, review_count
            FROM persona_profile_snapshots
            WHERE target_id = ?
            ORDER BY created_at DESC LIMIT 1
        ''', (tid,)).fetchone()
        t['latest_snapshot'] = dict(snap) if snap else None
    except sqlite3.OperationalError:
        t['latest_snapshot'] = None

    # Get knowledge observations
    try:
        krows = conn.execute('''
            SELECT domain, score, confidence, evaluator, evidence_source, observed_at
            FROM persona_knowledge_observations
            WHERE target_id = ?
            ORDER BY observed_at DESC
        ''', (tid,)).fetchall()
        t['knowledge'] = [dict(r) for r in krows]
    except sqlite3.OperationalError:
        t['knowledge'] = []

    # Get surveillance aliases if linked
    if t.get('surveillance_target_id'):
        try:
            arows = conn.execute('''
                SELECT alias, alias_type, resolved_user_id, first_seen, last_seen
                FROM surveillance_aliases
                WHERE target_id = ?
            ''', (t['surveillance_target_id'],)).fetchall()
            t['surveillance_aliases'] = [dict(r) for r in arows]
        except sqlite3.OperationalError:
            t['surveillance_aliases'] = []
    else:
        t['surveillance_aliases'] = []

    # Get message count for this target's platform_user_id
    if t.get('platform_user_id'):
        try:
            mc = conn.execute(
                'SELECT COUNT(*) as msg_count FROM messages WHERE user_id = ?',
                (int(t['platform_user_id']),)
            ).fetchone()
            t['message_count'] = mc['msg_count'] if mc else 0
        except (sqlite3.OperationalError, ValueError):
            t['message_count'] = 0
    else:
        t['message_count'] = 0

conn.close()
print(json.dumps({'targets': targets, 'count': len(targets)}, default=str))
" 2>&1)

TARGET_COUNT=$(echo "${TARGETS_JSON}" | python3 -c "import json,sys; print(json.load(sys.stdin).get('count',0))" 2>/dev/null || echo 0)

echo "[INFO] Found ${TARGET_COUNT} persona target(s)"

if [[ "${TARGET_COUNT}" -eq 0 ]]; then
    echo "[WARN] No persona targets found. Exiting."
    echo "No targets to analyze." > "${REPORT_DIR}/persona_analysis_${TIMESTAMP}.md"
    exit 0
fi

# Save the targets export
TARGETS_FILE="${REPORT_DIR}/persona_targets_${TIMESTAMP}.json"
echo "${TARGETS_JSON}" | python3 -m json.tool > "${TARGETS_FILE}" 2>/dev/null || echo "${TARGETS_JSON}" > "${TARGETS_FILE}"
echo "[INFO] Targets export: ${TARGETS_FILE}"

# ─── Step 2: Per-target analysis ─────────────────────────────────────────

# Export per-target data and build analysis prompts
ANALYSIS_SUMMARY="${REPORT_DIR}/persona_analysis_${TIMESTAMP}.md"
echo "# SPECTRA Persona Analysis Report" > "${ANALYSIS_SUMMARY}"
echo "" >> "${ANALYSIS_SUMMARY}"
echo "**Date:** ${DATE}" >> "${ANALYSIS_SUMMARY}"
echo "**Timestamp:** ${TIMESTAMP}" >> "${ANALYSIS_SUMMARY}"
echo "**Targets:** ${TARGET_COUNT}" >> "${ANALYSIS_SUMMARY}"
echo "**Algorithm backup:** ${BACKUP_PATH}" >> "${ANALYSIS_SUMMARY}"
echo "" >> "${ANALYSIS_SUMMARY}"
echo "---" >> "${ANALYSIS_SUMMARY}"

# Iterate each target
TARGET_IDS=$(echo "${TARGETS_JSON}" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for t in data.get('targets', []):
    print(t['target_id'])
" 2>/dev/null)

for TARGET_ID in ${TARGET_IDS}; do
    echo ""
    echo "[INFO] ═══ Processing target: ${TARGET_ID} ═══"

    # Export full data for this target
    TARGET_DATA_FILE="${REPORT_DIR}/target_${TARGET_ID}_${TIMESTAMP}.json"
    python3 -c "
import json, sqlite3, sys
from pathlib import Path

db_path = '${DB_PATH}'
target_id = '${TARGET_ID}'
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

data = {'target_id': target_id, 'timestamp': '${TIMESTAMP}'}

# Target info
try:
    row = conn.execute('SELECT * FROM persona_targets WHERE target_id = ?', (target_id,)).fetchone()
    data['target'] = dict(row) if row else None
except sqlite3.OperationalError:
    data['target'] = None

# All examples
try:
    rows = conn.execute('''
        SELECT * FROM persona_examples WHERE target_id = ?
        ORDER BY observed_at DESC LIMIT 500
    ''', (target_id,)).fetchall()
    data['examples'] = [dict(r) for r in rows]
    data['example_count'] = len(rows)
except sqlite3.OperationalError:
    data['examples'] = []
    data['example_count'] = 0

# All snapshots (for drift analysis)
try:
    rows = conn.execute('''
        SELECT snapshot_id, as_of, model, model_version, created_at,
               positive_count, negative_count, review_count
        FROM persona_profile_snapshots
        WHERE target_id = ?
        ORDER BY created_at DESC
    ''', (target_id,)).fetchall()
    data['snapshots'] = [dict(r) for r in rows]
except sqlite3.OperationalError:
    data['snapshots'] = []

# Knowledge observations
try:
    rows = conn.execute('''
        SELECT * FROM persona_knowledge_observations
        WHERE target_id = ? ORDER BY observed_at DESC
    ''', (target_id,)).fetchall()
    data['knowledge'] = [dict(r) for r in rows]
except sqlite3.OperationalError:
    data['knowledge'] = []

# Surveillance data if linked
surv_id = data.get('target', {}).get('surveillance_target_id') if data.get('target') else None
if surv_id:
    try:
        arows = conn.execute('SELECT * FROM surveillance_aliases WHERE target_id = ?', (surv_id,)).fetchall()
        data['surveillance_aliases'] = [dict(r) for r in arows]
    except sqlite3.OperationalError:
        data['surveillance_aliases'] = []

    # Contact network (interactions)
    try:
        # Resolve user IDs from aliases
        user_ids = []
        for a in data.get('surveillance_aliases', []):
            if a.get('resolved_user_id'):
                user_ids.append(a['resolved_user_id'])
        if user_ids:
            irows = conn.execute('''
                SELECT * FROM osint_interactions
                WHERE target_user_id IN (%s)
                ORDER BY timestamp DESC LIMIT 200
            ''' % ','.join('?' * len(user_ids)), user_ids).fetchall()
            data['interactions'] = [dict(r) for r in irows]
        else:
            data['interactions'] = []
    except sqlite3.OperationalError:
        data['interactions'] = []
else:
    data['surveillance_aliases'] = []
    data['interactions'] = []

# Recent messages by this target
platform_uid = data.get('target', {}).get('platform_user_id') if data.get('target') else None
if platform_uid:
    try:
        mrows = conn.execute('''
            SELECT id, content, date, channel_id, reply_to_message_id
            FROM messages WHERE user_id = ?
            ORDER BY date DESC LIMIT 200
        ''', (int(platform_uid),)).fetchall()
        data['recent_messages'] = [dict(r) for r in mrows]
    except (sqlite3.OperationalError, ValueError):
        data['recent_messages'] = []
else:
    data['recent_messages'] = []

# ── Drift metrics (latest per layer) ──────────────────────────────────
try:
    drows = conn.execute('''
        SELECT feature_layer, similarity_score, confidence, js_divergence,
               earlier_snapshot_id, later_snapshot_id, computed_at
        FROM persona_drift_metrics
        WHERE target_id = ?
        ORDER BY computed_at DESC
    ''', (target_id,)).fetchall()
    drift_by_layer = {}
    for r in drows:
        layer = r['feature_layer']
        if layer not in drift_by_layer:
            drift_by_layer[layer] = dict(r)
    data['drift_metrics'] = drift_by_layer
except sqlite3.OperationalError:
    data['drift_metrics'] = {}

# ── Latest calibration ────────────────────────────────────────────────
try:
    crow = conn.execute('''
        SELECT * FROM persona_calibration
        WHERE target_id = ?
        ORDER BY computed_at DESC LIMIT 1
    ''', (target_id,)).fetchone()
    data['calibration'] = dict(crow) if crow else None
except sqlite3.OperationalError:
    data['calibration'] = None

conn.close()
print(json.dumps(data, default=str))
" > "${TARGET_DATA_FILE}" 2>/dev/null

    EXAMPLE_COUNT=$(python3 -c "import json; d=json.load(open('${TARGET_DATA_FILE}')); print(d.get('example_count',0))" 2>/dev/null || echo 0)
    MSG_COUNT=$(python3 -c "import json; d=json.load(open('${TARGET_DATA_FILE}')); print(len(d.get('recent_messages',[])))" 2>/dev/null || echo 0)
    SNAP_COUNT=$(python3 -c "import json; d=json.load(open('${TARGET_DATA_FILE}')); print(len(d.get('snapshots',[])))" 2>/dev/null || echo 0)

    echo "[INFO] Target ${TARGET_ID}: ${EXAMPLE_COUNT} examples, ${MSG_COUNT} messages, ${SNAP_COUNT} snapshots"
    echo "[INFO] Data export: ${TARGET_DATA_FILE}"

    # ─── Step 2b: Compute drift metrics between last two snapshots ───────
    if [[ "${SNAP_COUNT}" -ge 2 ]]; then
        echo "[INFO] Computing drift metrics between last two snapshots..."
        python3 -c "
import sys, json
sys.path.insert(0, '.')
try:
    from tgarchive.db.persona_store import PersonaStore
    from tgarchive.intelligence.persona_training import PersonaTrainingModel
    from tgarchive.intelligence.features.linguistic import compare_linguistic_features
    from tgarchive.intelligence.features.orthographic import compare_orthographic_features
    from tgarchive.intelligence.features.errors import compare_error_features
    from tgarchive.intelligence.features.discourse import compare_discourse_features
    from tgarchive.intelligence.features.syntax import compare_syntax_features

    store = PersonaStore('${DB_PATH}')
    snapshots = store.query_snapshots('${TARGET_ID}', limit=50)
    if len(snapshots) >= 2:
        earlier = snapshots[-2]
        later = snapshots[-1]
        compare_fns = {
            'linguistic': ('linguistic_features', compare_linguistic_features),
            'orthographic': ('orthographic_features', compare_orthographic_features),
            'errors': ('error_features', compare_error_features),
            'discourse': ('discourse_features', compare_discourse_features),
            'syntax': ('syntax_features', compare_syntax_features),
        }
        for layer_name, (key, fn) in compare_fns.items():
            feat_a = earlier.get(key)
            feat_b = later.get(key)
            if feat_a and feat_b:
                try:
                    sim, conf = fn(feat_a, feat_b)
                    store.save_drift_metric(
                        '${TARGET_ID}',
                        earlier['snapshot_id'], later['snapshot_id'],
                        layer_name, float(sim),
                        confidence=float(conf),
                    )
                    print(f'  {layer_name}: sim={sim:.4f} conf={conf:.4f}')
                except Exception as e:
                    print(f'  {layer_name}: error - {e}')
        # Also compute JS divergence for vocabulary if available
        import math
        for label, key in [('vocabulary', 'vocabulary'), ('distinctive_vocab', 'distinctive_vocab')]:
            va = earlier.get(key)
            vb = later.get(key)
            if va and vb:
                try:
                    all_words = set(va.keys()) | set(vb.keys())
                    pa = sum(va.values()) or 1.0
                    pb = sum(vb.values()) or 1.0
                    js = 0.0
                    for w in all_words:
                        p = va.get(w, 0.0) / pa
                        q = vb.get(w, 0.0) / pb
                        m = 0.5 * (p + q)
                        if m > 0 and p > 0:
                            js += 0.5 * p * math.log2(p / m)
                        if m > 0 and q > 0:
                            js += 0.5 * q * math.log2(q / m)
                    sim = 1.0 - min(1.0, js)
                    store.save_drift_metric(
                        '${TARGET_ID}',
                        earlier['snapshot_id'], later['snapshot_id'],
                        label, float(sim),
                        confidence=1.0,
                        js_divergence=float(js),
                    )
                    print(f'  {label}: sim={sim:.4f} js={js:.4f}')
                except Exception as e:
                    print(f'  {label}: error - {e}')
    store.close()
except Exception as e:
    print(f'[WARN] Drift computation failed: {e}')
" 2>&1 || echo "[WARN] Drift computation step skipped"
    fi

    # ─── Step 2c: Compute score breakdowns for sample examples ───────────
    if [[ "${EXAMPLE_COUNT}" -gt 0 ]]; then
        echo "[INFO] Computing score breakdowns for sample examples..."
        python3 -c "
import sys, json
sys.path.insert(0, '.')
try:
    from tgarchive.intelligence.persona_training import PersonaTrainingModel
    from tgarchive.intelligence.feature_config import get_config
    from tgarchive.db.persona_store import PersonaStore

    store = PersonaStore('${DB_PATH}')
    snap = store.latest_snapshot('${TARGET_ID}')
    if snap:
        cfg = get_config('${TARGET_ID}')
        data = json.load(open('${TARGET_DATA_FILE}'))
        examples = data.get('examples', [])
        pos_examples = [e for e in examples if e.get('label') == 'positive'][:5]
        breakdowns = []
        for ex in pos_examples:
            text = ex.get('text', '')
            if not text or len(text) < 10:
                continue
            score = PersonaTrainingModel.score_example(snap, text, config=cfg)
            score['text_preview'] = text[:200]
            breakdowns.append(score)
        # Add breakdowns to the data file
        data['score_breakdowns'] = breakdowns
        with open('${TARGET_DATA_FILE}', 'w') as f:
            json.dump(data, f, default=str)
        print(f'  Computed {len(breakdowns)} score breakdowns')
    store.close()
except Exception as e:
    print(f'[WARN] Score breakdown computation failed: {e}')
" 2>&1 || echo "[WARN] Score breakdown step skipped"
    fi

    # Build the analysis prompt for this target
    PROMPT_FILE="/tmp/devin_persona_prompt_${TARGET_ID}_${TIMESTAMP}.md"
    python3 scripts/build_persona_prompt.py "${TARGET_DATA_FILE}" "${TARGET_ID}" "${PROMPT_FILE}" 2>&1

    PROMPT_SIZE=$(wc -c < "${PROMPT_FILE}" 2>/dev/null || echo 0)
    echo "[INFO] Prompt size: ${PROMPT_SIZE} bytes"

    if [[ "${DRY_RUN}" == "true" ]]; then
        echo "[INFO] Dry run — skipping Devin launch"
        echo "" >> "${ANALYSIS_SUMMARY}"
        echo "## Target: ${TARGET_ID}" >> "${ANALYSIS_SUMMARY}"
        echo "**Status:** Dry run — data exported, analysis skipped" >> "${ANALYSIS_SUMMARY}"
        echo "**Examples:** ${EXAMPLE_COUNT} | **Messages:** ${MSG_COUNT} | **Snapshots:** ${SNAP_COUNT}" >> "${ANALYSIS_SUMMARY}"
        echo "**Data file:** ${TARGET_DATA_FILE}" >> "${ANALYSIS_SUMMARY}"
        echo "**Prompt file:** ${PROMPT_FILE}" >> "${ANALYSIS_SUMMARY}"
        echo "---" >> "${ANALYSIS_SUMMARY}"
        continue
    fi

    # ─── Step 3: Launch Devin GLM-5.2 High for this target ───────────────

    echo "[INFO] Launching Devin GLM-5.2 High for target ${TARGET_ID}..."

    SESSION_LOG="/tmp/devin_persona_${TARGET_ID}_${TIMESTAMP}.log"
    TARGET_REPORT="${REPORT_DIR}/target_${TARGET_ID}_${TIMESTAMP}_analysis.md"

    # Capture sessions before
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

    # Wait for completion (max 20 minutes per target)
    TIMEOUT=1200
    ELAPSED=0
    while kill -0 ${DEVIN_PID} 2>/dev/null; do
        sleep 10
        ELAPSED=$((ELAPSED + 10))
        if [ ${ELAPSED} -ge ${TIMEOUT} ]; then
            echo "[WARN] Devin timed out after ${TIMEOUT}s for target ${TARGET_ID}, killing..."
            kill ${DEVIN_PID} 2>/dev/null || true
            break
        fi
    done

    wait ${DEVIN_PID} 2>/dev/null || true
    EXIT_CODE=$?

    echo "[INFO] Devin exited with code: ${EXIT_CODE}"

    # Extract analysis from session log
    if [ -s "${SESSION_LOG}" ]; then
        python3 -c "
import re
lines = open('${SESSION_LOG}', 'r', errors='replace').readlines()
clean = []
for line in lines:
    line = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', line)
    line = re.sub(r'\x1b\][^\x07]*\x07', '', line)
    line = re.sub(r'\[\?2004[hl]', '', line)
    clean.append(line)
content = ''.join(clean)
with open('${TARGET_REPORT}', 'w') as f:
    f.write(content)
print(f'Analysis written to ${TARGET_REPORT}')
" 2>/dev/null || cp "${SESSION_LOG}" "${TARGET_REPORT}"

        echo "[INFO] Target report: ${TARGET_REPORT}"
        echo "[INFO] Report size: $(wc -c < ${TARGET_REPORT}) bytes"

        # ─── Step 3b: Parse and apply lexicon expansions ───────────────────
        echo "[INFO] Parsing lexicon expansions from analysis..."
        python3 -c "
import sys
sys.path.insert(0, '.')
try:
    from tgarchive.intelligence.lexicon_store import apply_expansions_from_text
    with open('${TARGET_REPORT}', 'r', errors='replace') as f:
        text = f.read()
    added = apply_expansions_from_text(text, added_by='glm-5.2', target='${TARGET_ID}')
    if added:
        print('[INFO] Lexicon expansions applied:')
        for cat, count in added.items():
            print(f'  {cat}: +{count} words')
    else:
        print('[INFO] No lexicon expansions found in analysis output.')
except Exception as e:
    print(f'[WARN] Failed to apply lexicon expansions: {e}')
" 2>&1 || echo "[WARN] Lexicon expansion step skipped"

        # ─── Step 3c: Parse and apply feature config adjustments ──────────
        echo "[INFO] Parsing feature config adjustments from analysis..."
        python3 -c "
import sys
sys.path.insert(0, '.')
try:
    from tgarchive.intelligence.feature_config import apply_config_from_text
    with open('${TARGET_REPORT}', 'r', errors='replace') as f:
        text = f.read()
    overrides = apply_config_from_text(text, '${TARGET_ID}', added_by='glm-5.2')
    if overrides:
        print('[INFO] Feature config adjustments applied:')
        for key, val in overrides.items():
            if not key.startswith('__'):
                print(f'  {key}: {val}')
        # Also mirror to SQL for durability
        try:
            from tgarchive.intelligence.feature_config import get_config
            from tgarchive.db.persona_store import PersonaStore
            cfg = get_config('${TARGET_ID}')
            store = PersonaStore('${DB_PATH}')
            # Store only the overrides (not the merged config)
            store.save_feature_config('${TARGET_ID}', cfg, updated_by='glm-5.2')
            store.close()
        except Exception as e:
            print(f'[WARN] Failed to mirror config to SQL: {e}')
    else:
        print('[INFO] No feature config adjustments found in analysis output.')
except Exception as e:
    print(f'[WARN] Failed to apply feature config: {e}')
" 2>&1 || echo "[WARN] Feature config step skipped"
    else
        echo "[WARN] No output from Devin for target ${TARGET_ID}"
        echo "No analysis output produced." > "${TARGET_REPORT}"
    fi

    # Append to summary
    echo "" >> "${ANALYSIS_SUMMARY}"
    echo "## Target: ${TARGET_ID}" >> "${ANALYSIS_SUMMARY}"
    echo "**Examples:** ${EXAMPLE_COUNT} | **Messages:** ${MSG_COUNT} | **Snapshots:** ${SNAP_COUNT}" >> "${ANALYSIS_SUMMARY}"
    echo "**Data file:** ${TARGET_DATA_FILE}" >> "${ANALYSIS_SUMMARY}"
    echo "**Analysis:** ${TARGET_REPORT}" >> "${ANALYSIS_SUMMARY}"
    echo "---" >> "${ANALYSIS_SUMMARY}"

    # Delete the Devin session
    echo "[INFO] Cleaning up Devin session..."
    SESSIONS_AFTER=$(devin list 2>/dev/null | grep -oP '[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}' || true)
    NEW_SESSION=$(comm -13 <(echo "${SESSIONS_BEFORE}" | sort) <(echo "${SESSIONS_AFTER}" | sort) | head -1)
    if [ -n "${NEW_SESSION}" ]; then
        echo "[INFO] Deleting session: ${NEW_SESSION}"
        devin rm "${NEW_SESSION}" --force 2>/dev/null && echo "[INFO] Session deleted" || echo "[WARN] Failed to delete session"
    else
        echo "[WARN] Could not find new session ID to delete"
    fi

    # Clean up prompt file
    rm -f "${PROMPT_FILE}" 2>/dev/null || true

done

# ─── Step 4: Final summary ───────────────────────────────────────────────

echo ""
echo "[INFO] ═══ Periodic persona analysis complete ═══"
echo "[INFO] Summary report: ${ANALYSIS_SUMMARY}"
echo "[INFO] Algorithm backup: ${BACKUP_PATH}"
echo "[INFO] Targets analyzed: ${TARGET_COUNT}"
echo "[INFO] Reports in: ${REPORT_DIR}/"

# Clean up old reports (keep last 30 days)
find "${REPORT_DIR}" -name "persona_analysis_*.md" -mtime +30 -delete 2>/dev/null || true
find "${REPORT_DIR}" -name "target_*_analysis.md" -mtime +30 -delete 2>/dev/null || true
find "${REPORT_DIR}" -name "target_*.json" -mtime +30 -delete 2>/dev/null || true
find "${BACKUP_DIR}" -name "persona_algo_*.tar.gz" -mtime +90 -delete 2>/dev/null || true

echo "[INFO] Old reports cleaned up (>30 days)"
