#!/usr/bin/env bash
set -euo pipefail

readonly PRIMARY_UNIT="spectra-index.service"
readonly TASK_UNIT="spectra-index-tasks.service"
readonly PRIMARY_TRANSIENT_UNIT="spectra-index-live.service"
readonly TASK_TRANSIENT_UNIT="spectra-index-tasks-live.service"

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
unit_dir="/etc/systemd/system"
service_user="spectra"
service_group="spectra"
environment_file=""
project_dir=""
config_path=""
primary_database=""
task_database=""
python_path=""
enable_units=1
start_units=1
reload_units=1
force_start=0
uninstall=0

usage() {
    cat <<'EOF'
Usage:
  install-index-services.sh --project-dir PATH --config PATH \
    --database PATH --task-database PATH [OPTIONS]
  install-index-services.sh --uninstall [--unit-dir PATH] [--no-reload]

Required installation arguments:
  --project-dir PATH       SPECTRA checkout or installed project directory
  --config PATH            SPECTRA JSON configuration file
  --database PATH          Primary SQLite database
  --task-database PATH     Task/audit SQLite database

Options:
  --python PATH            Python interpreter (default: PROJECT/.venv/bin/python)
  --user USER              Service account (default: spectra)
  --group GROUP            Service group (default: spectra)
  --environment-file PATH  Optional credentials/environment file
  --unit-dir PATH          Unit destination (default: /etc/systemd/system)
  --no-enable              Install but do not enable units
  --no-start               Install and enable but do not start units
  --no-reload              Do not run systemctl daemon-reload
  --force-start            Start even when transient index user units are active
  --uninstall              Stop, disable, and remove only the durable index units
  -h, --help               Show this help

The installer never stops or modifies spectra-index-live.service or
spectra-index-tasks-live.service. When either transient unit is active, durable
units are installed and enabled but their initial start is deferred unless
--force-start is supplied.
EOF
}

die() {
    printf 'error: %s\n' "$*" >&2
    exit 2
}

require_value() {
    local option="$1"
    local value="${2-}"
    [[ -n "$value" ]] || die "$option requires a non-empty value"
}

while (($#)); do
    case "$1" in
        --project-dir)
            require_value "$1" "${2-}"
            project_dir="$2"
            shift 2
            ;;
        --config)
            require_value "$1" "${2-}"
            config_path="$2"
            shift 2
            ;;
        --database)
            require_value "$1" "${2-}"
            primary_database="$2"
            shift 2
            ;;
        --task-database)
            require_value "$1" "${2-}"
            task_database="$2"
            shift 2
            ;;
        --python)
            require_value "$1" "${2-}"
            python_path="$2"
            shift 2
            ;;
        --user)
            require_value "$1" "${2-}"
            service_user="$2"
            shift 2
            ;;
        --group)
            require_value "$1" "${2-}"
            service_group="$2"
            shift 2
            ;;
        --environment-file)
            require_value "$1" "${2-}"
            environment_file="$2"
            shift 2
            ;;
        --unit-dir)
            require_value "$1" "${2-}"
            unit_dir="$2"
            shift 2
            ;;
        --no-enable)
            enable_units=0
            shift
            ;;
        --no-start)
            start_units=0
            shift
            ;;
        --no-reload)
            reload_units=0
            shift
            ;;
        --force-start)
            force_start=1
            shift
            ;;
        --uninstall)
            uninstall=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown argument: $1"
            ;;
    esac
done

systemctl_command() {
    if ((EUID == 0)); then
        systemctl "$@"
    else
        sudo systemctl "$@"
    fi
}

install_file() {
    local source="$1"
    local destination="$2"
    if [[ -w "$(dirname -- "$destination")" ]]; then
        install -m 0644 "$source" "$destination"
    else
        sudo install -m 0644 "$source" "$destination"
    fi
}

remove_file() {
    local path="$1"
    if [[ -w "$(dirname -- "$path")" ]]; then
        rm -f -- "$path"
    else
        sudo rm -f -- "$path"
    fi
}

if ((uninstall)); then
    if ((reload_units)); then
        systemctl_command disable --now "$PRIMARY_UNIT" "$TASK_UNIT" 2>/dev/null || true
    fi
    remove_file "$unit_dir/$PRIMARY_UNIT"
    remove_file "$unit_dir/$TASK_UNIT"
    if ((reload_units)); then
        systemctl_command daemon-reload
        systemctl_command reset-failed "$PRIMARY_UNIT" "$TASK_UNIT" 2>/dev/null || true
    fi
    printf 'Removed %s and %s from %s.\n' "$PRIMARY_UNIT" "$TASK_UNIT" "$unit_dir"
    exit 0
fi

[[ -n "$project_dir" ]] || die "--project-dir is required"
[[ -n "$config_path" ]] || die "--config is required"
[[ -n "$primary_database" ]] || die "--database is required"
[[ -n "$task_database" ]] || die "--task-database is required"

project_dir="$(realpath -e -- "$project_dir")"
config_path="$(realpath -e -- "$config_path")"
primary_database="$(realpath -m -- "$primary_database")"
task_database="$(realpath -m -- "$task_database")"
unit_dir="$(realpath -m -- "$unit_dir")"
if [[ -z "$python_path" ]]; then
    python_path="$project_dir/.venv/bin/python"
fi
python_path="$(realpath -e -- "$python_path")"
if [[ -n "$environment_file" ]]; then
    environment_file="$(realpath -e -- "$environment_file")"
fi

[[ -d "$project_dir" ]] || die "project directory does not exist: $project_dir"
[[ -f "$config_path" ]] || die "config is not a regular file: $config_path"
[[ -x "$python_path" ]] || die "Python interpreter is not executable: $python_path"
[[ "$primary_database" != "$task_database" ]] || die "primary and task databases must differ"
command -v systemd-analyze >/dev/null || die "systemd-analyze is required"
getent passwd "$service_user" >/dev/null || die "service user does not exist: $service_user"
getent group "$service_group" >/dev/null || die "service group does not exist: $service_group"

primary_database_dir="$(dirname -- "$primary_database")"
task_database_dir="$(dirname -- "$task_database")"
[[ -d "$primary_database_dir" ]] || die "primary database directory does not exist: $primary_database_dir"
[[ -d "$task_database_dir" ]] || die "task database directory does not exist: $task_database_dir"

validate_unit_value() {
    local name="$1"
    local value="$2"
    [[ "$value" != *$'\n'* && "$value" != *$'\r'* ]] ||
        die "$name contains a newline"
}

for pair in \
    "project directory:$project_dir" \
    "config path:$config_path" \
    "primary database:$primary_database" \
    "task database:$task_database" \
    "Python path:$python_path" \
    "unit directory:$unit_dir"; do
    validate_unit_value "${pair%%:*}" "${pair#*:}"
done
if [[ -n "$environment_file" ]]; then
    validate_unit_value "environment file" "$environment_file"
fi

escape_unit_value() {
    local value="$1"
    value="${value//\\/\\\\}"
    value="${value//\"/\\\"}"
    value="${value//%/%%}"
    printf '%s' "$value"
}

escape_environment_path() {
    local value
    value="$(escape_unit_value "$1")"
    value="${value// /\\x20}"
    value="${value//$'\t'/\\x09}"
    printf '%s' "$value"
}

escape_sed_replacement() {
    local value="$1"
    value="${value//\\/\\\\}"
    value="${value//&/\\&}"
    value="${value//|/\\|}"
    printf '%s' "$value"
}

render_unit() {
    local template="$1"
    local output="$2"
    local database="$3"
    local database_dir="$4"
    local environment_directive=""
    local project_value config_value database_value database_dir_value
    local python_value user_value group_value environment_value

    if [[ -n "$environment_file" ]]; then
        environment_directive="EnvironmentFile=-$(escape_environment_path "$environment_file")"
    fi

    project_value="$(escape_sed_replacement "$(escape_unit_value "$project_dir")")"
    config_value="$(escape_sed_replacement "$(escape_unit_value "$config_path")")"
    database_value="$(escape_sed_replacement "$(escape_unit_value "$database")")"
    database_dir_value="$(escape_sed_replacement "$(escape_unit_value "$database_dir")")"
    python_value="$(escape_sed_replacement "$(escape_unit_value "$python_path")")"
    user_value="$(escape_sed_replacement "$service_user")"
    group_value="$(escape_sed_replacement "$service_group")"
    environment_value="$(escape_sed_replacement "$environment_directive")"

    sed \
        -e "s|@PROJECT_DIR@|$project_value|g" \
        -e "s|@CONFIG@|$config_value|g" \
        -e "s|@PRIMARY_DATABASE@|$database_value|g" \
        -e "s|@PRIMARY_DATABASE_DIR@|$database_dir_value|g" \
        -e "s|@TASK_DATABASE@|$database_value|g" \
        -e "s|@TASK_DATABASE_DIR@|$database_dir_value|g" \
        -e "s|@PYTHON@|$python_value|g" \
        -e "s|@SERVICE_USER@|$user_value|g" \
        -e "s|@SERVICE_GROUP@|$group_value|g" \
        -e "s|@ENVIRONMENT_FILE_DIRECTIVE@|$environment_value|g" \
        "$template" >"$output"
}

temporary_dir="$(mktemp -d)"
trap 'rm -rf -- "$temporary_dir"' EXIT
render_unit \
    "$script_dir/$PRIMARY_UNIT" \
    "$temporary_dir/$PRIMARY_UNIT" \
    "$primary_database" \
    "$primary_database_dir"
render_unit \
    "$script_dir/$TASK_UNIT" \
    "$temporary_dir/$TASK_UNIT" \
    "$task_database" \
    "$task_database_dir"

systemd-analyze verify \
    "$temporary_dir/$PRIMARY_UNIT" \
    "$temporary_dir/$TASK_UNIT"

if [[ -d "$unit_dir" && -w "$unit_dir" ]]; then
    :
elif mkdir -p -- "$unit_dir" 2>/dev/null; then
    chmod 0755 "$unit_dir"
elif ((EUID == 0)); then
    install -d -m 0755 "$unit_dir"
else
    sudo install -d -m 0755 "$unit_dir"
fi

changed=0
for unit in "$PRIMARY_UNIT" "$TASK_UNIT"; do
    if [[ ! -f "$unit_dir/$unit" ]] || ! cmp -s "$temporary_dir/$unit" "$unit_dir/$unit"; then
        install_file "$temporary_dir/$unit" "$unit_dir/$unit"
        printf 'Installed %s\n' "$unit_dir/$unit"
        changed=1
    else
        printf 'Unchanged %s\n' "$unit_dir/$unit"
    fi
done

if ((reload_units)); then
    systemctl_command daemon-reload
fi
if ((enable_units)); then
    systemctl_command enable "$PRIMARY_UNIT" "$TASK_UNIT"
fi

if ((start_units)); then
    transient_active=0
    caller_user="${SUDO_USER:-$(id -un)}"
    for transient in "$PRIMARY_TRANSIENT_UNIT" "$TASK_TRANSIENT_UNIT"; do
        if systemctl --user --machine="${caller_user}@.host" is-active --quiet "$transient" 2>/dev/null; then
            transient_active=1
            printf 'Active transient worker detected: %s\n' "$transient" >&2
        fi
    done
    if ((transient_active && !force_start)); then
        printf '%s\n' \
            "Durable units are enabled but were not started because transient index workers are active." \
            "Stop the transient units when convenient, then run:" \
            "  systemctl start $PRIMARY_UNIT $TASK_UNIT"
    elif ((changed)); then
        systemctl_command restart "$PRIMARY_UNIT" "$TASK_UNIT"
    else
        systemctl_command start "$PRIMARY_UNIT" "$TASK_UNIT"
    fi
fi

if ((changed == 0)); then
    printf 'Index service installation is already current.\n'
fi
