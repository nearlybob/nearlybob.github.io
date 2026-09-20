# -*- coding: utf-8 -*-
"""The popup's fixed section identities and their labels."""
from .strings import S

RECENT = 'recent'
VIDEO_SECTION = 'video_addons'
MUSIC_SECTION = 'music_addons'
PICTURES_SECTION = 'picture_addons'
PROGRAM_SECTION = 'program_addons'
SHORTCUTS_SECTION = 'shortcuts'
SYSTEM_SECTION = 'system'
CONFIGURE_SECTION = 'configure'  # always last; not reorderable, not hideable

SECTION_KEYS = [RECENT, VIDEO_SECTION, MUSIC_SECTION, PICTURES_SECTION, PROGRAM_SECTION,
                SHORTCUTS_SECTION, SYSTEM_SECTION]
SECTION_LABELS = {
    RECENT: S.SEC_RECENT, VIDEO_SECTION: S.SEC_VIDEO, MUSIC_SECTION: S.SEC_MUSIC,
    PICTURES_SECTION: S.SEC_PICTURES, PROGRAM_SECTION: S.SEC_PROGRAM,
    SHORTCUTS_SECTION: S.SEC_SHORTCUTS, SYSTEM_SECTION: S.SEC_SYSTEM,
    CONFIGURE_SECTION: S.SEC_CONFIGURE,
}
# For someone who already saved a section order: where sections added later slot in.
PLACE_AFTER = {MUSIC_SECTION: VIDEO_SECTION, PICTURES_SECTION: MUSIC_SECTION}
