include(FetchContent)

# Fix for SSL connection errors (revocation server offline)
set(CMAKE_TLS_VERIFY OFF)

message(STATUS "Configuring GoogleTest...")
FetchContent_Declare(
  googletest
  URL https://github.com/google/googletest/archive/refs/tags/v1.14.0.zip
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)

# For Windows: Prevent overriding the parent project's compiler/linker settings
set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)

message(STATUS "Downloading and building GoogleTest (this may take a minute)...")
FetchContent_MakeAvailable(googletest)
message(STATUS "GoogleTest setup complete.")

enable_testing()

add_executable(unit_tests
    test_orderbook.cpp
)

target_link_libraries(unit_tests
    PRIVATE
        gtest_main
        orderbook_lib
)

target_include_directories(unit_tests
    PRIVATE
        ../include
        ../src
)

include(GoogleTest)
gtest_discover_tests(unit_tests)
