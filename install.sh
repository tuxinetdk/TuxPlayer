#!/usr/bin/env bash
set -eu
umask 077

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
ENV_EXAMPLE="$SCRIPT_DIR/.env.example"
DATA_DIR="$SCRIPT_DIR/data"
TEMP_ENV_FILE=""

cleanup() {
  if [ -n "${TEMP_ENV_FILE:-}" ] && [ -f "$TEMP_ENV_FILE" ]; then
    rm -f "$TEMP_ENV_FILE"
  fi
}

trap cleanup EXIT INT TERM

assign_var() {
  printf -v "$1" '%s' "$2"
}

strip_carriage_return() {
  printf '%s' "${1%$'\r'}"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 1
  fi
}

dotenv_escape_single_quoted() {
  printf "%s" "$1" | sed "s/'/'\\\\''/g"
}

write_env_line() {
  key="$1"
  value="$2"
  printf "%s='%s'\n" "$key" "$(dotenv_escape_single_quoted "$value")" >> "$TEMP_ENV_FILE"
}

prompt_default() {
  var_name="$1"
  prompt_text="$2"
  default_value="$3"
  printf '%s [%s]: ' "$prompt_text" "$default_value"
  IFS= read -r input_value || true
  input_value="$(strip_carriage_return "$input_value")"
  if [ -z "$input_value" ]; then
    assign_var "$var_name" "$default_value"
  else
    assign_var "$var_name" "$input_value"
  fi
}

prompt_optional() {
  var_name="$1"
  prompt_text="$2"
  printf '%s: ' "$prompt_text"
  IFS= read -r input_value || true
  input_value="$(strip_carriage_return "$input_value")"
  assign_var "$var_name" "$input_value"
}

prompt_secret() {
  var_name="$1"
  prompt_text="$2"
  printf '%s: ' "$prompt_text"
  IFS= read -r -s input_value || true
  input_value="$(strip_carriage_return "$input_value")"
  printf '\n'
  assign_var "$var_name" "$input_value"
}

confirm_yes_no() {
  var_name="$1"
  prompt_text="$2"
  default_value="$3"
  printf '%s [%s]: ' "$prompt_text" "$default_value"
  IFS= read -r input_value || true
  input_value="$(strip_carriage_return "$input_value")"
  input_value="$(printf '%s' "${input_value:-$default_value}" | tr '[:upper:]' '[:lower:]')"
  case "$input_value" in
    y|yes) assign_var "$var_name" "yes" ;;
    n|no) assign_var "$var_name" "no" ;;
    *)
      printf 'Please answer yes or no.\n' >&2
      exit 1
      ;;
  esac
}

validate_admin_inputs() {
  if { [ -n "$admin_username" ] && [ -z "$admin_password" ]; } || { [ -z "$admin_username" ] && [ -n "$admin_password" ]; }; then
    printf 'Admin username and password must either both be provided or both be left empty.\n' >&2
    exit 1
  fi
}

write_env_file_atomically() {
  TEMP_ENV_FILE="$(mktemp "$SCRIPT_DIR/.env.tmp.XXXXXX")"
  write_env_line TZ "$tz"
  write_env_line PUBLIC_BASE_URL "$public_base_url"
  write_env_line STREAM_IDLE_TIMEOUT "$stream_idle_timeout"
  write_env_line STREAM_BITRATE "$stream_bitrate"
  write_env_line STREAM_SAMPLE_RATE "$stream_sample_rate"
  write_env_line STREAM_VOLUME "$stream_volume"
  write_env_line STREAM_CHUNK_MS "$stream_chunk_ms"
  write_env_line SUBSCRIBER_QUEUE_SIZE "$subscriber_queue_size"
  write_env_line STREAMLINK_LIVE_EDGE "$streamlink_live_edge"
  write_env_line STREAMLINK_QUALITY "$streamlink_quality"
  write_env_line TWITCH_CLIENT_ID "$twitch_client_id"
  write_env_line TWITCH_CLIENT_SECRET "$twitch_client_secret"
  write_env_line ADMIN_USERNAME "$admin_username"
  write_env_line ADMIN_PASSWORD "$admin_password"
  write_env_line LOG_LEVEL "$log_level"
  chmod 600 "$TEMP_ENV_FILE"
  mv -f "$TEMP_ENV_FILE" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  TEMP_ENV_FILE=""
}

main() {
  require_command docker

  if ! docker compose version >/dev/null 2>&1; then
    printf 'docker compose is required but not available.\n' >&2
    exit 1
  fi

  if [ ! -f "$ENV_EXAMPLE" ]; then
    printf 'Could not find %s\n' "$ENV_EXAMPLE" >&2
    exit 1
  fi

  mkdir -p "$DATA_DIR"

  printf 'TuxPlayer interactive installer\n'
  printf 'Project directory: %s\n\n' "$SCRIPT_DIR"

  if [ -f "$ENV_FILE" ]; then
    confirm_yes_no overwrite_env "An existing .env file was found. Overwrite it?" "no"
    if [ "$overwrite_env" = "no" ]; then
      printf 'Keeping existing .env. Installer aborted without changes.\n'
      exit 0
    fi
  fi

  prompt_default server_ip "Server IP or hostname for browser and Music Assistant access" "localhost"
  prompt_default public_base_url "Public base URL" "http://${server_ip}:8766"
  prompt_default tz "Timezone" "Europe/Copenhagen"
  prompt_default stream_idle_timeout "Stream idle timeout in seconds" "30"
  prompt_default stream_bitrate "Stream bitrate" "160k"
  prompt_default stream_sample_rate "Stream sample rate" "44100"
  prompt_default stream_volume "Default stream volume" "1.8"
  prompt_default stream_chunk_ms "Stream chunk size in ms" "50"
  prompt_default subscriber_queue_size "Subscriber queue size" "24"
  prompt_default streamlink_live_edge "Streamlink live edge" "3"
  prompt_default streamlink_quality "Streamlink quality" "best"
  prompt_optional twitch_client_id "Twitch Client ID (leave blank to disable Twitch API)"
  prompt_secret twitch_client_secret "Twitch Client Secret (leave blank to disable Twitch API)"
  prompt_optional admin_username "Admin username (leave blank to disable admin login)"
  prompt_secret admin_password "Admin password (leave blank to disable admin login)"
  prompt_default log_level "Log level" "INFO"

  validate_admin_inputs
  write_env_file_atomically

  printf '\nCreated %s\n' "$ENV_FILE"
  printf 'UI URL: %s\n' "$public_base_url"
  printf 'Stream URL: %s/stream/\n' "$public_base_url"

  confirm_yes_no start_now "Build and start TuxPlayer now with docker compose up -d --build?" "yes"
  if [ "$start_now" = "yes" ]; then
    (cd "$SCRIPT_DIR" && docker compose up -d --build)
    printf '\nTuxPlayer is starting.\n'
    printf 'Open: %s\n' "$public_base_url"
  else
    printf '\nTo start later, run:\n'
    printf 'cd %s && docker compose up -d --build\n' "$SCRIPT_DIR"
  fi
}

if [ "${TUXPLAYER_INSTALL_SOURCE_ONLY:-0}" != "1" ]; then
  main "$@"
fi
