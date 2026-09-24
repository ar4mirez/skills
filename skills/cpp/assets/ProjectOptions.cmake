# ProjectOptions.cmake: warnings, sanitizers, and hardening as ONE interface target.
# Link it PRIVATE, wrapped in $<BUILD_INTERFACE:...>, so these flags never leak to
# consumers of an installed library.
include_guard(GLOBAL)
include(CheckCXXSourceCompiles)
include(CheckPIESupported)

check_pie_supported()
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

add_library(acme_options INTERFACE)
add_library(acme::options ALIAS acme_options)

# --- Warnings ---------------------------------------------------------------
if(MSVC)
  target_compile_options(acme_options INTERFACE
    /W4 /permissive- /utf-8 /Zc:__cplusplus /w14265 /w14296 /w14826
    $<$<BOOL:${ACME_WARNINGS_AS_ERRORS}>:/WX>)
else()
  target_compile_options(acme_options INTERFACE
    -Wall -Wextra -Wpedantic
    -Wconversion -Wsign-conversion -Wshadow
    -Wnon-virtual-dtor -Wold-style-cast -Woverloaded-virtual
    -Wcast-align -Wnull-dereference -Wdouble-promotion
    -Wformat=2 -Wimplicit-fallthrough
    $<$<BOOL:${ACME_WARNINGS_AS_ERRORS}>:-Werror>)
endif()

# --- Sanitizers -------------------------------------------------------------
if(ACME_SANITIZERS)
  if("thread" IN_LIST ACME_SANITIZERS AND "address" IN_LIST ACME_SANITIZERS)
    message(FATAL_ERROR "ThreadSanitizer cannot be combined with AddressSanitizer")
  endif()
  list(JOIN ACME_SANITIZERS "," _san_list)
  if(MSVC)
    target_compile_options(acme_options INTERFACE /fsanitize=${_san_list})
  else()
    target_compile_options(acme_options INTERFACE
      -fsanitize=${_san_list} -fno-omit-frame-pointer -fno-sanitize-recover=all)
    target_link_options(acme_options INTERFACE -fsanitize=${_san_list})
  endif()
endif()

# --- Hardening (OpenSSF Compiler Options Hardening Guide) --------------------
if(ACME_HARDENING AND NOT MSVC)
  # Standard-library precondition checks. Each library ignores the other's macro,
  # so defining both is safe and avoids detecting which one is in use.
  target_compile_definitions(acme_options INTERFACE
    $<IF:$<CONFIG:Debug>,_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_DEBUG,_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST>
    _GLIBCXX_ASSERTIONS)

  target_compile_options(acme_options INTERFACE -fstack-protector-strong)

  # _FORTIFY_SOURCE needs optimization and conflicts with ASan; skip it in
  # Debug and sanitizer builds. -U first: some distros predefine a lower level.
  if(NOT ACME_SANITIZERS)
    target_compile_options(acme_options INTERFACE
      $<$<NOT:$<CONFIG:Debug>>:-U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=3>
      $<$<NOT:$<CONFIG:Debug>>:-ftrivial-auto-var-init=zero>)
  endif()

  if(CMAKE_SYSTEM_NAME STREQUAL "Linux")
    target_compile_options(acme_options INTERFACE -fstack-clash-protection)
    if(CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|AMD64|amd64)$")
      target_compile_options(acme_options INTERFACE -fcf-protection=full)
    elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "^(aarch64|arm64)$")
      target_compile_options(acme_options INTERFACE -mbranch-protection=standard)
    endif()
    target_link_options(acme_options INTERFACE
      LINKER:-z,relro LINKER:-z,now LINKER:-z,noexecstack
      LINKER:--as-needed LINKER:--no-copy-dt-needed-entries)
  endif()
endif()

# --- Fuzzing support probe ----------------------------------------------------
# Apple clang ships no libFuzzer runtime; detect instead of assuming.
if(ACME_BUILD_FUZZERS)
  set(CMAKE_REQUIRED_FLAGS "-fsanitize=fuzzer")
  set(CMAKE_REQUIRED_LINK_OPTIONS "-fsanitize=fuzzer")
  check_cxx_source_compiles([[
    #include <cstddef>
    #include <cstdint>
    extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t*, std::size_t) { return 0; }
  ]] ACME_HAS_LIBFUZZER)
  unset(CMAKE_REQUIRED_FLAGS)
  unset(CMAKE_REQUIRED_LINK_OPTIONS)
  if(NOT ACME_HAS_LIBFUZZER)
    message(WARNING "libFuzzer not available with this compiler; fuzz targets skipped")
    set(ACME_BUILD_FUZZERS OFF)
  endif()
endif()
