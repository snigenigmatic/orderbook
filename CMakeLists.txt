cmake_minimum_required(VERSION 3.16)

project(low_latency_orderbook LANGUAGES CXX)

option(ORDERBOOK_PORTABLE "Build without -march=native" OFF)
option(ORDERBOOK_BUILD_TESTS "Build unit tests" ON)
option(ORDERBOOK_BUILD_PYTHON "Build the lobcast Python extension" OFF)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Sensible defaults for performance testing
if (NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release)
endif()

# Create a library for the core logic
add_library(orderbook_lib STATIC
    src/feed.cpp
    src/dispatcher.cpp
    src/orderbook_map.cpp
    src/orderbook_vector.cpp
    src/latency.cpp
    src/fifo_book.cpp
    src/lobster.cpp
    src/backtest.cpp
    include/orderbook/backtest.hpp
    include/orderbook/fifo_book.hpp
    include/orderbook/lobster.hpp
    include/orderbook/dispatcher.hpp
    include/orderbook/feed.hpp
    include/orderbook/latency.hpp
    include/orderbook/messages.hpp
    include/orderbook/order.hpp
    include/orderbook/orderbook_base.hpp
    include/orderbook/orderbook_map.hpp
    include/orderbook/orderbook_vector.hpp
    include/orderbook/timing.hpp
)

target_include_directories(orderbook_lib
    PUBLIC
        include
    PRIVATE
        src
)

# Performance oriented flags (safe, not exotic)
if(MSVC)
    target_compile_options(orderbook_lib
        PRIVATE
            /W4
            /permissive-
    )
else()
    target_compile_options(orderbook_lib
        PRIVATE
            -O3
            $<$<NOT:$<BOOL:${ORDERBOOK_PORTABLE}>>:-march=native>
            -Wall
            -Wextra
            -Wpedantic
    )
endif()

# Linux specific, harmless elsewhere
if (UNIX AND NOT APPLE)
    target_link_libraries(orderbook_lib
        PRIVATE
            pthread
    )
endif()

# The main executable
add_executable(orderbook
    src/main.cpp
)

target_link_libraries(orderbook 
    PRIVATE 
        orderbook_lib
)

add_executable(bench_lobster
    src/bench_lobster.cpp
)

target_link_libraries(bench_lobster
    PRIVATE
        orderbook_lib
)

set_target_properties(orderbook_lib PROPERTIES POSITION_INDEPENDENT_CODE ON)

if (ORDERBOOK_BUILD_TESTS)
    enable_testing()
    add_subdirectory(tests)
endif()

if (ORDERBOOK_BUILD_PYTHON)
    find_package(Python 3.10 REQUIRED COMPONENTS Interpreter Development.Module)
    execute_process(
        COMMAND "${Python_EXECUTABLE}" -m nanobind --cmake_dir
        OUTPUT_STRIP_TRAILING_WHITESPACE OUTPUT_VARIABLE nanobind_ROOT)
    find_package(nanobind CONFIG REQUIRED)
    nanobind_add_module(_core NB_STATIC python/bindings.cpp)
    target_link_libraries(_core PRIVATE orderbook_lib)
    install(TARGETS _core LIBRARY DESTINATION lobcast)
endif()
