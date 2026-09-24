# Cross-compile with `zig cc` (bundled clang + musl/glibc headers), e.g. static
# Linux binaries from a macOS laptop:
#   cmake -S . -B build/linux-x64 -G Ninja -DCMAKE_TOOLCHAIN_FILE=cmake/zig-toolchain.cmake \
#         -DZIG_TARGET=x86_64-linux-musl -DCMAKE_BUILD_TYPE=Release -DKVSTORE_STATIC=ON
# ZIG_TARGET examples: x86_64-linux-musl, aarch64-linux-musl, x86_64-linux-gnu.2.39
set(ZIG_TARGET "x86_64-linux-musl" CACHE STRING "zig target triple")

string(REGEX MATCH "^[^-]+" _zig_arch "${ZIG_TARGET}")
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR ${_zig_arch})
set(CMAKE_C_COMPILER zig cc -target ${ZIG_TARGET}) # a list = compiler + fixed args

# CMake would otherwise pick the host ar/ranlib, and Apple's ranlib silently
# produces archives lld cannot read ("undefined symbol" at link time).
# CMAKE_AR can't take arguments, so point it at tiny wrapper scripts.
set(_zig_wrappers "${CMAKE_BINARY_DIR}/zig-wrappers")
foreach(tool IN ITEMS ar ranlib)
  if(NOT EXISTS "${_zig_wrappers}/${tool}")
    file(CONFIGURE OUTPUT "${_zig_wrappers}/${tool}" CONTENT "#!/bin/sh\nexec zig ${tool} \"$@\"\n")
    file(CHMOD "${_zig_wrappers}/${tool}" PERMISSIONS OWNER_READ OWNER_WRITE OWNER_EXECUTE GROUP_READ GROUP_EXECUTE WORLD_READ WORLD_EXECUTE)
  endif()
endforeach()
set(CMAKE_AR "${_zig_wrappers}/ar" CACHE FILEPATH "zig ar" FORCE)
set(CMAKE_RANLIB "${_zig_wrappers}/ranlib" CACHE FILEPATH "zig ranlib" FORCE)
