cmake_minimum_required(VERSION 3.16)
project(example DESCRIPTION "examples how to use LogHelper lib")


set(CMAKE_BUILD_TYPE Release)

add_executable(
        example
        example_log.c
)


include_directories(example ${CMAKE_SOURCE_DIR}/include)
target_link_libraries(example ${CMAKE_SOURCE_DIR}/build/libLogHelper.so)
link_directories(${CMAKE_SOURCE_DIR}/build)