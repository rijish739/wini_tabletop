cmake_minimum_required(VERSION 3.12)
project(alphabet_ui C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# This module's own lv_conf.h (absolute path, so LVGL and our sources agree).
add_compile_definitions(LV_CONF_PATH=${CMAKE_CURRENT_SOURCE_DIR}/lv_conf.h)

find_package(SDL2 REQUIRED)
include_directories(${SDL2_INCLUDE_DIRS})

# Reuse the tutor UI's LVGL v9 checkout rather than vendoring a second copy —
# one engine, one version, and `wini_ui` stays the place LVGL is updated.
set(WINI_UI_DIR ${CMAKE_CURRENT_SOURCE_DIR}/../../wini_ui)
if(NOT EXISTS ${WINI_UI_DIR}/lvgl/lvgl.h)
    message(FATAL_ERROR
        "LVGL not found at ${WINI_UI_DIR}/lvgl — check out the tutor UI's LVGL v9 first.")
endif()
add_subdirectory(${WINI_UI_DIR}/lvgl ${CMAKE_CURRENT_BINARY_DIR}/lvgl)

file(GLOB ALPHA_SRC CONFIGURE_DEPENDS
    ${CMAKE_CURRENT_SOURCE_DIR}/theme/*.c
    ${CMAKE_CURRENT_SOURCE_DIR}/fonts/*.c
    ${CMAKE_CURRENT_SOURCE_DIR}/screens/*.c
)

add_executable(alphabet_ui
    main.c
    ipc.c
    ${ALPHA_SRC}
)

# WINI_UI_DIR is on the include path so `#include "lvgl/lvgl.h"` resolves the
# same way it does in the tutor UI (and inside the generated font files).
target_include_directories(alphabet_ui PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${WINI_UI_DIR}
)
target_link_libraries(alphabet_ui PRIVATE lvgl ${SDL2_LIBRARIES} m pthread)
