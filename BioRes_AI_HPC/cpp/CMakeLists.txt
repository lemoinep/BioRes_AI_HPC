add_executable(biores_worker
    src/main.cpp
)

target_include_directories(biores_worker
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/include
)

if(MSVC)
    target_compile_options(biores_worker
        PRIVATE
            /W4
    )
else()
    target_compile_options(biores_worker
        PRIVATE
            -Wall
            -Wextra
            -Wpedantic
    )
endif()

if(BIORES_BUILD_TESTS)
    enable_testing()
endif()