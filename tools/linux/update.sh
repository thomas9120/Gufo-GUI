#!/usr/bin/env bash
# Fast-forward official Gufo main and rebuild; the standalone GUI stays separate.
set -o pipefail
# shellcheck source=common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
stop_label="Update"

update_usage() {
  cat <<'EOF'
Usage: update-linux.sh [options]
  --gufo-path PATH  Official Gufo checkout (default: the folder saved by setup)
  --rocm PATH       ROCm installation prefix (default: the saved or detected prefix)
  --jobs N          Parallel build jobs, 1-64 (default: 4)
EOF
}

parse_update_args() {
  gufo_path="" rocm="" jobs=4
  while (( $# )); do
    case $1 in
      --gufo-path) [[ $# -ge 2 ]] || die "$1 needs a value."; gufo_path=$2; shift ;;
      --rocm) [[ $# -ge 2 ]] || die "$1 needs a value."; rocm=$2; shift ;;
      --jobs) [[ $# -ge 2 ]] || die "$1 needs a value."; jobs=$2; shift ;;
      -h|--help) update_usage; exit 0 ;;
      *) update_usage >&2; die "Unknown option: $1" ;;
    esac
    shift
  done
  [[ $jobs =~ ^[0-9]+$ ]] && (( jobs >= 1 && jobs <= 64 )) || die "--jobs must be from 1 to 64."
}

run_linux_update() {
  parse_update_args "$@"
  resolve_engine_root "$gufo_path"
  detect_setup_tools "$rocm"
  [[ -n $rocm_path ]] || missing_system+=("ROCm development files")
  if (( ${#missing_system[@]} )); then
    die "Build prerequisites are missing ($(join_list "${missing_system[@]}")). Run setup-linux.sh first."
  fi
  assert_engine_stopped
  assert_gufo_source "$git_bin"
  info "Updating official Gufo main at $engine_root..."
  setup_command "$git_bin" -C "$engine_root" pull --ff-only --no-rebase --no-autostash "$repository" main
  assert_engine_stopped
  save_setup_state
  build_gufo
  verify_engine
  printf '\n'
  success "Update complete: $engine"
  printf 'Run ./launch-gui.sh. Saved presets are preserved.\n'
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  run_linux_update "$@"
fi
