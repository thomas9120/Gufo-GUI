# Shared helpers for Linux setup and update. Source this file; it changes nothing by itself.
# shellcheck shell=bash

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)
state_file="$root/build/linux-setup.json"
repository="https://github.com/gufo-org/gufo.git"
preset="release"
stop_label="Setup"
rocm_cmake_packages=(hip hipblas hipblaslt rocblas)
rocm_headers=(hipcub/hipcub.hpp rocprim/rocprim.hpp rocwmma/rocwmma.hpp)
pkg_modules=(icu-uc icu-i18n libcurl openssl libpng libjpeg libwebp sndfile soxr)

if [[ -t 1 ]]; then color_info=$'\e[36m' color_good=$'\e[32m' color_bad=$'\e[31m' color_off=$'\e[0m'
else color_info="" color_good="" color_bad="" color_off=""; fi

info() { printf '%s%s%s\n' "$color_info" "$*" "$color_off"; }
success() { printf '%s%s%s\n' "$color_good" "$*" "$color_off"; }

join_list() {
  local IFS=$'\x1f' items
  items="$*"
  printf '%s' "${items//$'\x1f'/, }"
}

die() {
  printf '\n%s%s stopped: %s%s\n' "$color_bad" "$stop_label" "$*" "$color_off" >&2
  exit 1
}

setup_command() {
  "$@" || die "$1 failed (exit $?). See the output above."
}

resolve_engine_root() {
  local selected=$1
  [[ -n $selected ]] || selected=$(saved_value GufoPath)
  [[ -n $selected ]] || selected="$root/gufo"
  engine_root=$(realpath -m -- "$selected")
  [[ $engine_root != "$root" ]] || die "Gufo needs a separate folder from the GUI repository. Use --gufo-path or the default gufo subfolder."
  engine="$engine_root/build/$preset/gufo"
}

saved_value() {
  # Missing or unreadable state means "detect again", just like a first run.
  local python
  python=$(command -v python3) || return 0
  [[ -f $state_file ]] || return 0
  "$python" -I - "$state_file" "$1" 2>/dev/null <<'EOF' || true
import json, sys
value = json.load(open(sys.argv[1], encoding="utf-8-sig")).get(sys.argv[2])
if isinstance(value, str):
    print(value)
EOF
}

save_setup_state() {
  mkdir -p -- "$(dirname -- "$state_file")" || die "Cannot create $(dirname -- "$state_file")."
  "${python_bin:-python3}" -I - "$state_file" GufoPath "$engine_root" Git "$git_bin" CMake "$cmake_bin" \
    Ninja "$ninja_bin" Python "$python_bin" Rocm "$rocm_path" <<'EOF' || die "Cannot write $state_file."
import json, os, sys
path, pairs = sys.argv[1], sys.argv[2:]
with open(path + ".tmp", "w", encoding="utf-8") as file:
    json.dump(dict(zip(pairs[::2], pairs[1::2])), file, indent=2)
os.replace(path + ".tmp", path)
EOF
}

version_at_least() {
  printf '%s\n%s\n' "$2" "$1" | sort -V -C
}

find_program() {
  # Usage: find_program MINIMUM CANDIDATE...; prints the first suitable path.
  local minimum=$1 candidate path output
  shift
  for candidate in "$@"; do
    [[ -n $candidate ]] || continue
    path=$(command -v -- "$candidate" 2>/dev/null) || continue
    output=$("$path" --version 2>/dev/null) || continue
    [[ $output =~ ([0-9]+\.[0-9]+(\.[0-9]+)?) ]] || continue
    if version_at_least "${BASH_REMATCH[1]}" "$minimum"; then
      printf '%s\n' "$path"
      return 0
    fi
  done
  return 1
}

find_python() {
  local candidate path
  for candidate in "$@"; do
    [[ -n $candidate ]] || continue
    path=$(command -v -- "$candidate" 2>/dev/null) || continue
    if "$path" -I -c "import struct,sys; assert sys.version_info >= (3,10) and struct.calcsize('P') == 8" 2>/dev/null; then
      printf '%s\n' "$path"
      return 0
    fi
  done
  return 1
}

rocm_missing_parts() {
  # Prints the ROCm development pieces upstream's CMake needs but cannot find under $1.
  local prefix=$1 package header
  for package in "${rocm_cmake_packages[@]}"; do
    [[ -d $prefix/lib/cmake/$package || -d $prefix/lib64/cmake/$package ]] || printf '%s\n' "$package"
  done
  for header in "${rocm_headers[@]}"; do
    [[ -f $prefix/include/$header ]] || printf '%s\n' "${header%%/*}"
  done
}

rocm_hip_compiler() {
  local candidate
  for candidate in "$1/llvm/bin/clang++" "$1/lib/llvm/bin/clang++" "$1/lib64/rocm/llvm/bin/clang++"; do
    if [[ -x $candidate ]]; then printf '%s\n' "$candidate"; return 0; fi
  done
  return 1
}

detect_setup_tools() {
  local requested_rocm=$1 candidate
  git_bin=$(find_program 2.0 "$(saved_value Git)" git) || git_bin=""
  cmake_bin=$(find_program 3.21 "$(saved_value CMake)" cmake) || cmake_bin=""
  ninja_bin=$(find_program 1.10 "$(saved_value Ninja)" ninja ninja-build) || ninja_bin=""
  cxx_bin=$(find_program 11 "${CXX:-}" c++ g++ clang++) || cxx_bin=""
  pkg_config_bin=$(find_program 0.2 pkg-config pkgconf) || pkg_config_bin=""
  python_bin=$(find_python "$(saved_value Python)" "$root/build/gui-env/bin/python" python3 \
    python3.14 python3.13 python3.12 python3.11 python3.10) || python_bin=""
  missing_system=()
  [[ -n $git_bin ]] || missing_system+=("Git 2+")
  [[ -n $cmake_bin ]] || missing_system+=("CMake 3.21+")
  [[ -n $ninja_bin ]] || missing_system+=("Ninja 1.10+")
  [[ -n $cxx_bin ]] || missing_system+=("C++20 compiler")
  [[ -n $pkg_config_bin ]] || missing_system+=("pkg-config")
  if [[ -z $python_bin ]]; then missing_system+=("64-bit Python 3.10+")
  elif ! "$python_bin" -I -c "import ensurepip, venv" 2>/dev/null; then missing_system+=("Python venv support")
  fi
  if [[ -n $pkg_config_bin ]]; then
    for candidate in "${pkg_modules[@]}"; do
      "$pkg_config_bin" --exists "$candidate" || missing_system+=("$candidate (development files)")
    done
  fi
  for candidate in ffmpeg ffprobe; do
    command -v "$candidate" >/dev/null || missing_system+=("$candidate")
  done
  if [[ -n $requested_rocm && -n $(rocm_missing_parts "$requested_rocm") ]]; then
    die "--rocm must point to a ROCm installation with hipBLAS, hipBLASLt, rocBLAS, hipCUB, rocPRIM and rocWMMA development files."
  fi
  rocm_path=""
  for candidate in "$requested_rocm" "$(saved_value Rocm)" "${ROCM_PATH:-}" "${HIP_PATH:-}" /opt/rocm /usr; do
    if [[ -n $candidate && -d $candidate && -z $(rocm_missing_parts "$candidate") ]]; then
      rocm_path=$(realpath -- "$candidate")
      break
    fi
  done
}

detect_package_manager() {
  if command -v apt-get >/dev/null; then
    package_manager=(apt-get install -y)
    system_packages=(build-essential cmake ninja-build pkg-config git python3 python3-venv libicu-dev
      libcurl4-openssl-dev libssl-dev libpng-dev libjpeg-dev libwebp-dev libsndfile1-dev libsoxr-dev ffmpeg)
    rocm_packages="hipblas-dev hipblaslt-dev rocblas-dev hipcub-dev rocprim-dev rocwmma-dev"
  elif command -v dnf >/dev/null; then
    package_manager=(dnf install -y)
    system_packages=(gcc-c++ cmake ninja-build pkgconf-pkg-config git python3 libicu-devel libcurl-devel
      openssl-devel libpng-devel libjpeg-turbo-devel libwebp-devel libsndfile-devel soxr-devel ffmpeg-free)
    rocm_packages="rocm-hip-devel hipblas-devel hipblaslt-devel rocblas-devel hipcub-devel rocprim-devel rocwmma-devel"
  elif command -v pacman >/dev/null; then
    package_manager=(pacman -S --needed --noconfirm)
    system_packages=(base-devel cmake ninja pkgconf git python icu curl openssl libpng libjpeg-turbo
      libwebp libsndfile libsoxr ffmpeg)
    rocm_packages="rocm-hip-sdk hipblas hipblaslt rocblas hipcub rocprim rocwmma"
  else
    package_manager=()
    system_packages=()
    rocm_packages=""
  fi
}

install_system_packages() {
  local -a elevate=()
  [[ $(id -u) -eq 0 ]] || elevate=(sudo)
  info "Installing system packages with ${package_manager[0]}..."
  setup_command "${elevate[@]}" "${package_manager[@]}" "${system_packages[@]}"
}

assert_setup_machine() {
  local cpu
  [[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || die "Use 64-bit x86 Linux on AMD Strix Halo."
  cpu=$(sed -n 's/^model name[[:space:]]*:[[:space:]]*//p' /proc/cpuinfo 2>/dev/null | head -n 1)
  if ! grep -qiE 'Ryzen[[:space:]]+AI[[:space:]]+MAX' <<<"$cpu"; then
    die "This setup targets AMD Ryzen AI Max (Strix Halo/gfx1151). Detected: ${cpu:-unknown CPU}"
  fi
  printf 'Computer: %s, %s\n' "$cpu" "$(. /etc/os-release 2>/dev/null && printf '%s' "${PRETTY_NAME:-Linux}")"
  if [[ ! -r /dev/kfd || ! -w /dev/kfd ]]; then
    printf 'Warning: this user cannot open /dev/kfd. Add it to the render and video groups, then log out and back in.\n'
  fi
}

assert_engine_stopped() {
  local pid exe
  command -v pgrep >/dev/null || return 0
  for pid in $(pgrep -x gufo); do
    exe=$(readlink "/proc/$pid/exe" 2>/dev/null) || exe=""
    if [[ -z $exe || $exe == "$engine" || $exe == "$engine (deleted)" ]]; then
      die "Gufo is running (PID $pid). Stop it in the launcher before rebuilding it."
    fi
  done
}

assert_gufo_source() {
  local git=$1 top remote branch changes
  local official='^(https://github\.com/gufo-org/gufo(\.git)?/?|git@github\.com:gufo-org/gufo(\.git)?)$'
  [[ -e $engine_root/.git ]] || die "No Gufo checkout at $engine_root. Run setup-linux.sh first."
  top=$("$git" -C "$engine_root" rev-parse --show-toplevel) && [[ $(realpath -- "$top") == "$engine_root" ]] ||
    die "GufoPath must be the root of its own Git checkout."
  remote=$("$git" -C "$engine_root" config --get remote.origin.url) && [[ $remote =~ $official ]] ||
    die "The checkout at $engine_root is not official gufo-org/gufo. Choose a separate folder with --gufo-path; existing forks are not converted."
  branch=$("$git" -C "$engine_root" symbolic-ref --quiet --short HEAD) && [[ $branch == main ]] ||
    die "Check out main in $engine_root before setup or update."
  changes=$("$git" -C "$engine_root" status --porcelain --untracked-files=all) && [[ -z $changes ]] ||
    die "The Gufo checkout has local changes or untracked files. Commit, stash or move them before setup/update."
}

initialize_gufo_source() {
  local git=$1
  if [[ ! -e $engine_root ]] || [[ -d $engine_root && ! -e $engine_root/.git && -z $(ls -A -- "$engine_root") ]]; then
    setup_command "$git" clone --branch main --single-branch "$repository" "$engine_root"
  fi
  assert_gufo_source "$git"
}

build_gufo() {
  local compiler
  local -a configure=(--preset "$preset" "-DCMAKE_MAKE_PROGRAM=$ninja_bin" -DGUFO_ENABLE_WARNINGS=OFF
    "-DCMAKE_PREFIX_PATH=$rocm_path")
  [[ -f $engine_root/CMakePresets.json ]] || die "Missing upstream CMakePresets.json in $engine_root. Update official Gufo main first."
  # A system Clang found first cannot compile HIP for gfx1151.
  if compiler=$(rocm_hip_compiler "$rocm_path"); then configure+=("-DCMAKE_HIP_COMPILER=$compiler"); fi
  (
    cd -- "$engine_root" &&
      PATH="$rocm_path/bin:$PATH" "$cmake_bin" "${configure[@]}" &&
      PATH="$rocm_path/bin:$PATH" "$cmake_bin" --build --preset "$preset" --target gufo --parallel "$jobs"
  ) || die "Official Gufo build failed (exit $?). See the compiler output above."
  [[ -x $engine ]] || die "The build completed without producing build/$preset/gufo."
}

verify_engine() {
  info "Checking the built executable and GPU (no model is loaded)..."
  setup_command "$engine" --version
  setup_command "$engine" diagnose --section gpu
}

assert_setup_space() {
  local required=$1 path free mount
  local -A seen=()
  for path in "$root" "$engine_root"; do
    while [[ ! -e $path ]]; do path=$(dirname -- "$path"); done
    read -r free mount < <(df -Pk -- "$path" | awk 'NR == 2 { print $4, $6 }')
    [[ -n $mount && -z ${seen[$mount]:-} ]] || continue
    seen[$mount]=1
    printf '  Free space on %s: %s GiB\n' "$mount" "$(awk -v k="$free" 'BEGIN { printf "%.1f", k / 1048576 }')"
    (( free >= required * 1048576 )) || die "Keep at least $required GiB free for setup/build files (models need additional space)."
  done
}
