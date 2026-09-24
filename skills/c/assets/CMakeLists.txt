# kvstore: library + CLI + service, one CMake project.
# Rules: target_* commands only (no global flags), warnings and hardening live
# on INTERFACE targets linked PRIVATE, -Werror comes from the CI preset
# (CMAKE_COMPILE_WARNING_AS_ERROR), never hard-coded here.
cmake_minimum_required(VERSION 3.25...4.4)
project(kvstore VERSION 0.1.0 LANGUAGES C)

option(KVSTORE_BUILD_TESTS "Build unit tests" ${PROJECT_IS_TOP_LEVEL})
option(KVSTORE_HARDENING "Add OpenSSF hardening flags supported by the toolchain" ON)
option(KVSTORE_SANITIZE "Build with ASan + UBSan (dev/test only)" OFF)
option(KVSTORE_TSAN "Build with ThreadSanitizer (dev/test only)" OFF)
option(KVSTORE_FUZZ "Build the libFuzzer target (LLVM clang, not Apple clang)" OFF)
option(KVSTORE_STATIC "Link executables fully static (musl toolchains)" OFF)

if(KVSTORE_SANITIZE AND KVSTORE_TSAN)
  message(FATAL_ERROR "ASan and TSan cannot be combined; pick one preset")
endif()

include(CheckCCompilerFlag)
include(CheckLinkerFlag)
include(CheckPIESupported)
include(GNUInstallDirs)
check_pie_supported() # makes POSITION_INDEPENDENT_CODE also pass -pie at link time

# ---- warnings ---------------------------------------------------------------
add_library(kvstore_warnings INTERFACE)
target_compile_options(kvstore_warnings INTERFACE
  $<$<C_COMPILER_ID:GNU,Clang,AppleClang>:
    -Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion -Wshadow
    -Wformat=2 -Wimplicit-fallthrough -Wstrict-prototypes -Wmissing-prototypes
    -Wvla -Wcast-qual -Wundef -Wnull-dereference
    -Werror=format-security -Werror=implicit -Werror=incompatible-pointer-types
    -Werror=int-conversion>
  $<$<C_COMPILER_ID:GNU>:-Wtrampolines -Wlogical-op -Wduplicated-cond -Wduplicated-branches>
  $<$<C_COMPILER_ID:MSVC>:/W4>)

# ---- hardening (OpenSSF Compiler Options Hardening Guide) --------------------
# Probe each flag instead of switching on OS/arch: -fcf-protection is x86-only,
# -mbranch-protection is AArch64-only, -fstack-clash-protection is ignored by
# Apple clang, and ld64 rejects every -z option.
add_library(kvstore_hardening INTERFACE)
if(KVSTORE_HARDENING AND NOT MSVC)
  set(_hardening_cflags
    -fstack-protector-strong -fstack-clash-protection -fstrict-flex-arrays=3
    -ftrivial-auto-var-init=zero -fno-delete-null-pointer-checks
    -fno-strict-overflow -fno-strict-aliasing
    -fcf-protection=full -mbranch-protection=standard)
  # -fno-strict-overflow makes signed overflow wrap, which silences UBSan's
  # signed-integer-overflow check: keep it out of sanitizer builds.
  if(KVSTORE_SANITIZE)
    list(REMOVE_ITEM _hardening_cflags -fno-strict-overflow)
  endif()
  # Probe under -Werror: Apple clang only *warns* about flags it ignores
  # (-fstack-clash-protection), which check_c_compiler_flag counts as success.
  set(CMAKE_REQUIRED_FLAGS -Werror)
  foreach(flag IN LISTS _hardening_cflags)
    string(MAKE_C_IDENTIFIER "HAVE_C${flag}" var)
    check_c_compiler_flag("${flag}" ${var})
    if(${var})
      target_compile_options(kvstore_hardening INTERFACE ${flag})
    endif()
  endforeach()
  unset(CMAKE_REQUIRED_FLAGS)
  # _FORTIFY_SOURCE needs optimization and conflicts with sanitizers.
  if(NOT KVSTORE_SANITIZE AND NOT KVSTORE_TSAN)
    target_compile_options(kvstore_hardening INTERFACE
      $<$<CONFIG:Release,RelWithDebInfo,MinSizeRel>:-U_FORTIFY_SOURCE -D_FORTIFY_SOURCE=3>)
  endif()
  foreach(flag IN ITEMS "-Wl,-z,relro" "-Wl,-z,now" "-Wl,-z,noexecstack" "-Wl,-z,nodlopen")
    string(MAKE_C_IDENTIFIER "HAVE_LD${flag}" var)
    check_linker_flag(C "${flag}" ${var})
    if(${var})
      target_link_options(kvstore_hardening INTERFACE ${flag})
    endif()
  endforeach()
endif()

# ---- sanitizers --------------------------------------------------------------
add_library(kvstore_sanitizers INTERFACE)
if(KVSTORE_SANITIZE)
  target_compile_options(kvstore_sanitizers INTERFACE
    -fsanitize=address,undefined -fno-sanitize-recover=all -fno-omit-frame-pointer)
  target_link_options(kvstore_sanitizers INTERFACE -fsanitize=address,undefined)
elseif(KVSTORE_TSAN)
  target_compile_options(kvstore_sanitizers INTERFACE -fsanitize=thread -fno-omit-frame-pointer)
  target_link_options(kvstore_sanitizers INTERFACE -fsanitize=thread)
endif()

# One place to apply the project policy to a target.
function(kvstore_target_defaults target)
  set_target_properties(${target} PROPERTIES
    C_STANDARD 23 C_STANDARD_REQUIRED ON C_EXTENSIONS OFF
    C_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN ON
    POSITION_INDEPENDENT_CODE ON)
  # BUILD_INTERFACE: a static library's PRIVATE deps still land in its export
  # set; these policy targets must not leak into installed kvstoreConfig.cmake.
  target_link_libraries(${target} PRIVATE
    $<BUILD_INTERFACE:kvstore_warnings>
    $<BUILD_INTERFACE:kvstore_hardening>
    $<BUILD_INTERFACE:kvstore_sanitizers>)
endfunction()

# ---- library -----------------------------------------------------------------
add_library(kvstore src/kvstore.c src/arena.c)
add_library(kvstore::kvstore ALIAS kvstore)
target_sources(kvstore PUBLIC
  FILE_SET HEADERS BASE_DIRS include FILES include/kvstore/kvstore.h)
target_include_directories(kvstore PRIVATE src)
kvstore_target_defaults(kvstore)
set_target_properties(kvstore PROPERTIES VERSION ${PROJECT_VERSION} SOVERSION 0)

install(TARGETS kvstore EXPORT kvstoreTargets FILE_SET HEADERS)
install(EXPORT kvstoreTargets NAMESPACE kvstore::
  FILE kvstoreConfig.cmake DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/kvstore)

function(kvstore_executable target)
  add_executable(${target} ${ARGN})
  target_link_libraries(${target} PRIVATE kvstore::kvstore)
  kvstore_target_defaults(${target})
  if(KVSTORE_STATIC)
    check_linker_flag(C "-static-pie" HAVE_LD_STATIC_PIE)
    if(HAVE_LD_STATIC_PIE)
      target_link_options(${target} PRIVATE -static-pie)
    else()
      set_target_properties(${target} PROPERTIES POSITION_INDEPENDENT_CODE OFF)
      target_link_options(${target} PRIVATE -static)
    endif()
  endif()
endfunction()

# >>> cli
kvstore_executable(kvstore-cli app/cli.c)
install(TARGETS kvstore-cli)
# <<< cli

# >>> service
add_library(kvstore_http STATIC app/http_handler.c)
target_include_directories(kvstore_http PUBLIC app)
target_link_libraries(kvstore_http PUBLIC kvstore::kvstore)
kvstore_target_defaults(kvstore_http)

find_package(Threads REQUIRED)
kvstore_executable(kvstore-server app/server.c)
target_link_libraries(kvstore-server PRIVATE kvstore_http Threads::Threads)
target_compile_definitions(kvstore-server PRIVATE _POSIX_C_SOURCE=200809L)
install(TARGETS kvstore-server)
# <<< service

# ---- tests -------------------------------------------------------------------
if(KVSTORE_BUILD_TESTS)
  enable_testing()
  find_package(Threads REQUIRED)
  kvstore_executable(test_kvstore tests/test_kvstore.c)
  target_link_libraries(test_kvstore PRIVATE Threads::Threads)
  add_test(NAME kvstore COMMAND test_kvstore)
  # >>> service
  kvstore_executable(test_http tests/test_http.c)
  target_link_libraries(test_http PRIVATE kvstore_http)
  add_test(NAME http COMMAND test_http)
  # <<< service
  # >>> cli
  file(WRITE ${CMAKE_CURRENT_BINARY_DIR}/sample.kv "greeting = hello\n")
  add_test(NAME cli_found COMMAND kvstore-cli ${CMAKE_CURRENT_BINARY_DIR}/sample.kv greeting)
  set_tests_properties(cli_found PROPERTIES PASS_REGULAR_EXPRESSION "^hello\n$")
  add_test(NAME cli_missing COMMAND kvstore-cli ${CMAKE_CURRENT_BINARY_DIR}/sample.kv nope)
  set_tests_properties(cli_missing PROPERTIES WILL_FAIL ON) # exit 1 = not found
  # <<< cli
endif()

# ---- fuzzing -----------------------------------------------------------------
if(KVSTORE_FUZZ)
  kvstore_executable(fuzz_parse fuzz/fuzz_parse.c)
  target_compile_options(fuzz_parse PRIVATE -fsanitize=fuzzer)
  target_link_options(fuzz_parse PRIVATE -fsanitize=fuzzer)
elseif(KVSTORE_BUILD_TESTS)
  # Without libFuzzer, replay a seed so the harness keeps compiling and running.
  kvstore_executable(fuzz_replay fuzz/fuzz_parse.c)
  target_compile_definitions(fuzz_replay PRIVATE KVSTORE_FUZZ_REPLAY)
  file(WRITE ${CMAKE_CURRENT_BINARY_DIR}/seed.txt "a=1\n# c\nb = two\n")
  add_test(NAME fuzz_replay COMMAND fuzz_replay ${CMAKE_CURRENT_BINARY_DIR}/seed.txt)
endif()
