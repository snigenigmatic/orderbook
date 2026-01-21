cmake_minimum_required(VERSION 3.16)

project(low_latency_orderbook LANGUAGES CXX)

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
            -march=native
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

# Enable testing
enable_testing()
add_subdirectory(tests)
