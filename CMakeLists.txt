cmake_minimum_required(VERSION 3.15)
project(pyccobs LANGUAGES C)

set(BUILD_SHARED_LIBS ON CACHE BOOL "Build ccobs as a shared library" FORCE)
set(BUILD_TESTING OFF CACHE BOOL "Do not build ccobs's C tests for the wheel" FORCE)

add_subdirectory(vendor/ccobs)

install(
    TARGETS ccobs
    LIBRARY DESTINATION ccobs
    RUNTIME DESTINATION ccobs
)
