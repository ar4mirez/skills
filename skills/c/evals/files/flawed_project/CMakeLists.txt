cmake_minimum_required(VERSION 3.0)
project(confd C)

set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -O2 -g -Werror")
include_directories(include)
add_definitions(-DCONFD_VERSION="1.0")

file(GLOB SOURCES src/*.c)
add_executable(confd ${SOURCES})
target_link_libraries(confd pthread)
