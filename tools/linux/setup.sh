#!/usr/bin/env bash
# Guided source setup. Source this file to exercise helpers without installing anything.
set -o pipefail
# shellcheck source=common.sh
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

setup_usage() {
  cat <<'EOF'
Usage: setup-linux.sh [options]
  --gufo-path PATH  Official Gufo checkout (default: ./gufo or the saved folder)
  --rocm PATH       ROCm installation prefix (default: detect /opt/rocm or /usr)
  --jobs N          Parallel build jobs, 1-64 (default: 4)
  --check-only      Show the plan without installing or building
  --yes             Accept the plan without asking
  --no-launch       Do not open the launcher when setup completes
EOF
}

parse_setup_args() {
  gufo_path="" rocm="" jobs=4 check_only=0 assume_yes=0 no_launch=0
  while (( $# )); do
    case $1 in
      --gufo-path) [[ $# -ge 2 ]] || die "$1 needs a value."; gufo_path=$2; shift ;;
      --rocm) [[ $# -ge 2 ]] || die "$1 needs a value."; rocm=$2; shift ;;
      --jobs) [[ $# -ge 2 ]] || die "$1 needs a value."; jobs=$2; shift ;;
      --check-only) check_only=1 ;;
      --yes|-y) assume_yes=1 ;;
      --no-launch) no_launch=1 ;;
      -h|--help) setup_usage; exit 0 ;;
      *) setup_usage >&2; die "Unknown option: $1" ;;
    esac
    shift
  done
  [[ $jobs =~ ^[0-9]+$ ]] && (( jobs >= 1 && jobs <= 64 )) || die "--jobs must be from 1 to 64."
}

print_setup_plan() {
  local tool
  printf '\n'
  info "Gufo setup plan"
  printf '  Official source: %s (main) -> %s\n' "$repository" "$engine_root"
  for tool in "Git:$git_bin" "CMake:$cmake_bin" "Ninja:$ninja_bin" "C++ compiler:$cxx_bin" "pkg-config:$pkg_config_bin" "Python:$python_bin"; do
    [[ -z ${tool#*:} ]] || printf '  Reuse %s: %s\n' "${tool%%:*}" "${tool#*:}"
  done
  if (( ${#missing_system[@]} )); then
    printf '  Missing: %s\n' "$(join_list "${missing_system[@]}")"
    if (( ${#package_manager[@]} )); then
      printf '  Install with %s: %s\n' "${package_manager[0]}" "${system_packages[*]}"
    fi
  fi
  if [[ -n $rocm_path ]]; then
    printf '  Reuse ROCm: %s%s\n' "$rocm_path" "$( [[ -f $rocm_path/.info/version ]] && printf ' (%s)' "$(head -n 1 "$rocm_path/.info/version")")"
  else
    printf '  ROCm: not found. Upstream qualifies ROCm 7.2.3 with hipBLAS, hipBLASLt, rocBLAS, hipCUB, rocPRIM and rocWMMA.\n'
  fi
  printf '  Build Gufo (%s preset), verify GPU startup, prepare the GUI. Existing GUI settings are preserved.\n' "$preset"
}

require_rocm() {
  [[ -z $rocm_path ]] || return 0
  printf '\nInstall ROCm first: https://rocm.docs.amd.com/projects/install-on-linux/en/latest/\n'
  [[ -z $rocm_packages ]] || printf 'Development packages for this distribution: %s\n' "$rocm_packages"
  printf 'For a nonstandard prefix, rerun with --rocm PATH.\n'
  die "ROCm development files were not found."
}

run_linux_setup() {
  local log answer fresh=5
  parse_setup_args "$@"
  resolve_engine_root "$gufo_path"
  assert_setup_machine
  assert_engine_stopped
  detect_setup_tools "$rocm"
  detect_package_manager
  if [[ -n $git_bin && -e $engine_root/.git ]]; then assert_gufo_source "$git_bin"; fi
  print_setup_plan
  [[ -e $engine_root/build/$preset ]] || fresh=25
  assert_setup_space "$fresh"
  if (( check_only )); then
    printf 'Preview only; nothing installed or changed.\n'
    return 0
  fi
  require_rocm
  if (( ${#missing_system[@]} )) && (( ! ${#package_manager[@]} )); then
    die "Install the missing tools listed above with your package manager, then rerun setup-linux.sh."
  fi
  if (( ! assume_yes )); then
    read -r -p "Continue with this plan? Package installation may ask for your sudo password [y/N] " answer || answer=""
    if [[ ! $answer =~ ^([yY]|[yY][eE][sS])$ ]]; then
      printf 'Setup cancelled. Nothing installed.\n'
      return 0
    fi
  fi
  mkdir -p -- "$root/build" || die "Cannot create $root/build."
  log="$root/build/setup-$(date +%Y%m%d-%H%M%S).log"
  exec 3>&1 4>&2
  exec > >(tee -a -- "$log") 2>&1
  printf 'Detailed setup log: %s\n' "$log"
  if (( ${#missing_system[@]} )); then
    install_system_packages
    hash -r
    detect_setup_tools "$rocm"
    if (( ${#missing_system[@]} )); then
      die "Still unavailable after installation: $(join_list "${missing_system[@]}"). Install them manually, then rerun setup-linux.sh."
    fi
  fi
  save_setup_state
  initialize_gufo_source "$git_bin"
  assert_engine_stopped
  info "Building Gufo. The first build can take a while..."
  build_gufo
  verify_engine
  setup_command bash "$root/tools/linux/gui.sh" --python "$python_bin" --prepare-only
  printf '\n'
  success "Setup complete. Next time, run ./launch-gui.sh."
  printf 'Select your model files in the GUI and save. Existing saved executable selections are unchanged; new settings default to %s.\n' "$engine"
  exec 1>&3 2>&4 3>&- 4>&-
  if (( ! no_launch )); then exec bash "$root/tools/linux/gui.sh"; fi
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then
  run_linux_setup "$@"
fi
