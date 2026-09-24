cmake_minimum_required(VERSION 3.1)
project(inventory CXX)

set(CMAKE_BUILD_TYPE Release)
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -std=gnu++17 -O3 -ffast-math -Werror")

include_directories(include)
add_definitions(-DINVENTORY_VERSION="1.0")

file(GLOB SOURCES src/*.cpp)
add_executable(inventory ${SOURCES})
target_link_libraries(inventory pthread)
