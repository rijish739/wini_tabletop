cmake_minimum_required(VERSION 3.12)
project(wini_ui C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Our minimal lv_conf.h — passed as an absolute path so both LVGL and our
# sources include it (lv_conf_internal.h fills every macro we don't override).
add_compile_definitions(LV_CONF_PATH=${CMAKE_CURRENT_SOURCE_DIR}/lv_conf.h)

# SDL2 must be found BEFORE add_subdirectory(lvgl) so LVGL's SDL driver compiles.
find_package(SDL2 REQUIRED)
include_directories(${SDL2_INCLUDE_DIRS})

# LVGL v9 (checked out at wini_ui/lvgl — see README: submodule or a v9 clone).
add_subdirectory(lvgl)

# Component tree — one directory per layer (theme, chrome, widgets, overlays,
# screens, app, platform) plus the generated serif fonts. CONFIGURE_DEPENDS
# re-globs when files are added, so new components need no edits here.
file(GLOB WINI_SRC CONFIGURE_DEPENDS
    ${CMAKE_CURRENT_SOURCE_DIR}/theme/*.c
    ${CMAKE_CURRENT_SOURCE_DIR}/fonts/*.c
    ${CMAKE_CURRENT_SOURCE_DIR}/chrome/*.c
    ${CMAKE_CURRENT_SOURCE_DIR}/widgets/*.c
    ${CMAKE_CURRENT_SOURCE_DIR}/overlays/*.c
    ${CMAKE_CURRENT_SOURCE_DIR}/screens/*.c
    ${CMAKE_CURRENT_SOURCE_DIR}/app/*.c
    ${CMAKE_CURRENT_SOURCE_DIR}/platform/*.c
)

add_executable(wini_ui
    main.c
    ipc.c
    ${WINI_SRC}
)
target_include_directories(wini_ui PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(wini_ui PRIVATE lvgl ${SDL2_LIBRARIES} m pthread)
